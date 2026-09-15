"""
agent.py — the agent layer.

Design principle: the four engines are pure, deterministic, testable functions.
The agent never does arithmetic or judgement itself — it only decides WHICH
tool to call, with WHAT arguments, and how to narrate the result. That keeps
the numbers auditable and the LLM replaceable.

`TOOLS` below is written as standard JSON-schema function specs, so the same
registry drops into any agent platform (Bob, a bare tool-calling API, or an
orchestration framework) via a thin adapter — see `PlatformAdapter`.

Guardrails are enforced here, not in the prompt:
  * every action above an approval threshold returns `requires_human_approval`
  * every recommendation carries its numeric rationale
  * the agent has read access to everything and write access to nothing except
    a proposal queue
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

TOOLS = [
    {
        "name": "assess_disruption_impact",
        "description": "Given active disruptions, return every in-flight shipment "
                       "that still has to transit an affected node, ranked by an "
                       "exposure score blending value at risk, SLA headroom, cargo "
                       "fragility, disruption severity and time-to-choke.",
        "input_schema": {
            "type": "object",
            "properties": {
                "disruption_id": {"type": "string",
                                  "description": "Optional. Limit to one disruption."},
                "min_score": {"type": "number", "default": 0},
                "limit": {"type": "integer", "default": 25},
            },
        },
    },
    {
        "name": "recommend_reroute",
        "description": "For an exposed shipment, generate and score alternatives "
                       "(hold, physical bypass, carrier/mode shift) on expected "
                       "total cost = SLA penalty + spoilage + incremental freight. "
                       "Returns options ranked with savings versus doing nothing.",
        "input_schema": {
            "type": "object",
            "properties": {"shipment_id": {"type": "string"}},
            "required": ["shipment_id"],
        },
    },
    {
        "name": "find_idle_assets",
        "description": "List fleet assets idle beyond their kind-specific threshold, "
                       "with accumulated carrying cost.",
        "input_schema": {
            "type": "object",
            "properties": {
                "near_node": {"type": "string"},
                "radius_km": {"type": "number", "default": 4500},
                "reefer_only": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "propose_redeployment",
        "description": "Match idle assets to demand signals raised by reroutes and "
                       "baseline lane throughput, minimising repositioning cost per "
                       "dollar of capacity released.",
        "input_schema": {
            "type": "object",
            "properties": {"max_repo_km": {"type": "number", "default": 4500}},
        },
    },
    {
        "name": "analyse_cold_chain",
        "description": "Parse IoT sensor logs for a shipment (or all cold shipments), "
                       "compute Mean Kinetic Temperature and cumulative time-out-of-"
                       "range, consume the product stability budget, and classify the "
                       "excursion as GREEN/AMBER/ORANGE/RED with the regulatory hook "
                       "and the required disposition action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {"type": "string"},
                "min_severity": {"type": "string",
                                 "enum": ["GREEN", "AMBER", "ORANGE", "RED"]},
            },
        },
    },
    {
        "name": "draft_stakeholder_notice",
        "description": "Draft the customer / QA / carrier notification for a decision "
                       "already taken. Never sends — returns text for approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "shipment_id": {"type": "string"},
                "audience": {"type": "string",
                             "enum": ["customer", "qa", "carrier", "regulator"]},
            },
            "required": ["shipment_id", "audience"],
        },
    },
]

APPROVAL_RULES = {
    "incremental_cost_usd": 25_000,
    "always_approve_classes": ["vaccine_2_8", "biologic_frozen"],
    "always_approve_severity": ["RED"],
}


@dataclass
class PlatformAdapter:
    """Thin seam between the tool registry and whatever agent runtime is used.

    To run on a specific platform, implement `call_model(system, messages, tools)`
    so it returns either {"text": str} or {"tool_call": {"name", "arguments"}}.
    Nothing else in the codebase changes.
    """
    call_model: Callable[[str, list, list], dict] | None = None

    def supports_tools(self) -> bool:
        return self.call_model is not None


SYSTEM_PROMPT = """You are SentinelChain, the supply chain control-tower agent.

You have four capabilities: disruption impact assessment, re-routing, fleet
redeployment, and cold-chain excursion classification.

Rules you never break:
1. You do not compute numbers yourself. Call a tool and quote what it returns.
2. Every recommendation you give must include: the dollar delta versus doing
   nothing, the assumption that drives it, and the confidence.
3. Anything above the approval threshold, anything touching a vaccine or frozen
   biologic, and any RED cold-chain disposition is a PROPOSAL, never an action.
   Say so explicitly.
4. If a tool returns nothing, say nothing was found. Do not fill the gap.
5. For cold-chain answers, always name the regulatory hook and the disposition.

Answer an operator in 5 lines or fewer, then offer the detail."""


class OfflineRouter:
    """Deterministic intent router so the demo runs with no network.

    In production this is replaced by the platform's tool-calling model; the
    tool signatures are identical, which is the whole point of the seam.
    """

    RULES = [
        (("cold", "temperature", "excursion", "reefer", "vaccine", "mkt"),
         "analyse_cold_chain"),
        (("idle", "utilisation", "utilization", "redeploy", "asset", "fleet"),
         "propose_redeployment"),
        (("reroute", "re-route", "alternative", "carrier", "divert", "option"),
         "recommend_reroute"),
        (("impact", "affected", "exposed", "disruption", "strike", "typhoon", "risk"),
         "assess_disruption_impact"),
        (("notify", "email", "notice", "tell the customer"),
         "draft_stakeholder_notice"),
    ]

    def route(self, query: str) -> str:
        q = query.lower()
        for keys, tool in self.RULES:
            if any(k in q for k in keys):
                return tool
        return "assess_disruption_impact"


def needs_approval(*, incremental_cost_usd=0, commodity_class=None, severity=None):
    return (incremental_cost_usd > APPROVAL_RULES["incremental_cost_usd"]
            or commodity_class in APPROVAL_RULES["always_approve_classes"]
            or severity in APPROVAL_RULES["always_approve_severity"])


def draft_notice(ship, audience, context):
    """Deterministic templates — an LLM can rewrite the prose, not the facts."""
    if audience == "qa":
        return (f"QA ACTION — {ship.shipment_id} ({ship.commodity_class}, "
                f"{ship.units} units, ${ship.value_usd:,}).\n"
                f"Severity {context['severity']} under {context['regulatory_hook']}. "
                f"MKT {context['mkt_c']}°C against a {context['label_range']} label; "
                f"{context['tor_minutes']} min out of range = "
                f"{context['budget_consumed_pct']:.0%} of stability budget.\n"
                f"Required disposition: {context['disposition']}\n"
                f"Detected {context['hours_to_delivery']}h before delivery — "
                f"intervention window is open.")
    if audience == "customer":
        return (f"Update on {ship.shipment_id}. An active disruption affects your "
                f"routing. Our recommended action is {context.get('recommendation')}, "
                f"which protects the delivery window at an incremental cost of "
                f"${context.get('incremental_cost_usd', 0):,.0f}. "
                f"We need your confirmation before we execute.")
    if audience == "carrier":
        return (f"Booking amendment request — {ship.shipment_id}. "
                f"Requesting {context.get('recommendation')}. "
                f"Please confirm space and revised ETA within 4h.")
    return (f"Regulatory file note — {ship.shipment_id}. Excursion classified "
            f"{context.get('severity')} per {context.get('regulatory_hook')}. "
            f"Full sensor profile and MKT derivation attached.")
