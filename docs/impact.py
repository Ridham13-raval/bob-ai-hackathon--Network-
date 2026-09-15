"""
impact.py — "which of my shipments does this disruption actually touch?"

A disruption is attached to one or more network nodes. A shipment is exposed
if any node it has NOT yet cleared appears in the disruption's node set.
Exposure is then scored so an operator sees the worst 20 rows, not all 140.

Exposure score (0-100) blends five signals:
    value at risk, SLA headroom, cargo fragility, disruption severity,
    and how soon the shipment hits the affected node.
"""
from __future__ import annotations

from datetime import datetime, timedelta

FRAGILITY = {
    "vaccine_2_8": 1.00,
    "biologic_frozen": 0.95,
    "perishable_food": 0.80,
    "pharma_ambient": 0.45,
    "electronics": 0.30,
    "automotive": 0.20,
}
PRIORITY_W = {"critical": 1.0, "high": 0.72, "standard": 0.45}


def _iso(s):
    return datetime.fromisoformat(s)


def remaining_nodes(ship) -> list:
    """Nodes still ahead of the shipment.

    Includes the node it is currently departing: a port closure or strike at
    the origin of the active leg still holds the box, the paperwork and the
    feeder connection."""
    return ship.route[ship.leg_index:]


def days_to_node(ship, node, now) -> float:
    """Rough time-to-arrival at a downstream node, linear over remaining legs."""
    rem = remaining_nodes(ship)
    if node not in rem:
        return 0.0
    total_legs = len(ship.route) - 1
    legs_left = total_legs - ship.leg_index
    eta = _iso(ship.eta)
    total_days_left = max(0.25, (eta - now).total_seconds() / 86400)
    per_leg = total_days_left / max(1, legs_left)
    return round(per_leg * (rem.index(node) + 1), 2)


def assess(shipments, disruptions, now):
    """Returns a list of exposure records, highest score first."""
    out = []
    for d in disruptions:
        hit_nodes = set(d.nodes)
        for s in shipments:
            rem = set(remaining_nodes(s))
            touched = sorted(hit_nodes & rem)
            if not touched:
                continue
            node = touched[0]
            lead_days = days_to_node(s, node, now)

            sla_slack = (_iso(s.sla_deadline) - _iso(s.eta)).total_seconds() / 86400
            delay = d.added_transit_days * d.severity
            projected_late = round(delay - sla_slack, 2)

            frag = FRAGILITY[s.commodity_class]
            value_w = min(1.0, s.value_usd / 1_500_000)
            urgency = 1.0 if lead_days < 1 else max(0.25, 1.6 / (1 + lead_days))
            sla_w = 1.0 if projected_late > 0 else 0.35

            score = 100 * (
                0.30 * value_w
                + 0.22 * frag
                + 0.20 * sla_w * min(1.0, max(0.0, projected_late) / 5 + 0.5)
                + 0.16 * d.severity
                + 0.12 * urgency * PRIORITY_W[s.priority]
            )

            out.append(dict(
                disruption_id=d.disruption_id,
                disruption=d.headline,
                kind=d.kind,
                shipment_id=s.shipment_id,
                customer=s.customer,
                commodity_class=s.commodity_class,
                value_usd=s.value_usd,
                carrier=s.carrier,
                mode=s.mode,
                choke_node=node,
                days_until_choke=lead_days,
                projected_delay_days=round(delay, 2),
                sla_slack_days=round(sla_slack, 2),
                sla_breach=projected_late > 0,
                projected_late_days=max(0.0, projected_late),
                priority=s.priority,
                exposure_score=round(score, 1),
            ))
    out.sort(key=lambda r: -r["exposure_score"])
    return out


def rollup(exposures):
    """Per-disruption summary for the exec view."""
    by = {}
    for e in exposures:
        b = by.setdefault(e["disruption_id"], dict(
            disruption_id=e["disruption_id"], headline=e["disruption"],
            kind=e["kind"], shipments=0, value_at_risk=0,
            sla_breaches=0, cold_chain=0, top_score=0.0))
        b["shipments"] += 1
        b["value_at_risk"] += e["value_usd"]
        b["sla_breaches"] += int(e["sla_breach"])
        b["cold_chain"] += int(e["commodity_class"] in
                               ("vaccine_2_8", "biologic_frozen", "perishable_food"))
        b["top_score"] = max(b["top_score"], e["exposure_score"])
    return sorted(by.values(), key=lambda r: -r["value_at_risk"])
