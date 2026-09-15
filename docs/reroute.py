"""
reroute.py — generate and score alternatives for an exposed shipment.

Three families of option are generated:
  1. HOLD        — ride it out (always scored, so the AI has to beat doing nothing)
  2. REROUTE     — same carrier/mode, different physical path around the choke node
  3. MODE_SHIFT  — different carrier and/or mode (ocean -> air/rail/road)

Each option is scored on a single utility that an ops manager can defend:
    utility = penalty_avoided - incremental_cost - risk_premium
All figures are USD. Nothing is a black box: every option carries its own
`rationale` string listing the numbers that produced its score.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .world import CARRIERS, NODES, haversine_km

# Physical detours that bypass a chokepoint, with the extra transit they cost.
BYPASS = {
    "EGSUZ": [("Cape of Good Hope", ["ZADUR"], 11.0, 0.18)],
    "NLRTM": [("Antwerp relay", ["DEHAM"], 1.5, 0.09),
              ("Hamburg discharge + rail", ["DEHAM"], 2.0, 0.14)],
    "CNSHA": [("Ningbo substitution", ["CNSZX"], 1.0, 0.07)],
    "CNSZX": [("Shanghai substitution", ["CNSHA"], 1.2, 0.07)],
    "AEJEA": [("Khalifa Port swing", ["AEJEA"], 0.5, 0.05)],
    "PABLB": [("Suez routing", ["EGSUZ"], 6.0, 0.12)],
}

# Penalty model
SPOILAGE_EXPOSURE = {
    "vaccine_2_8": 0.85, "biologic_frozen": 0.80, "perishable_food": 0.65,
    "pharma_ambient": 0.12, "electronics": 0.0, "automotive": 0.0,
}
SLA_PENALTY_PER_DAY = {"critical": 0.030, "high": 0.016, "standard": 0.006}
BASE_FREIGHT_PER_1K_VALUE = 38.0   # baseline freight spend proxy


def _freight_baseline(ship):
    return max(2500.0, ship.value_usd / 1000 * BASE_FREIGHT_PER_1K_VALUE)


def _penalty(ship, late_days, spoil_prob):
    """Expected USD cost of a given outcome."""
    sla = ship.value_usd * SLA_PENALTY_PER_DAY[ship.priority] * max(0.0, late_days)
    spoil = ship.value_usd * spoil_prob
    return sla + spoil


def options_for(ship, exposure, now):
    """Build the candidate set for one exposed shipment."""
    choke = exposure["choke_node"]
    base_late = exposure["projected_late_days"]
    base_freight = _freight_baseline(ship)
    cold = SPOILAGE_EXPOSURE[ship.commodity_class] > 0.3
    opts = []

    # ---- 1. HOLD ----------------------------------------------------
    hold_spoil = SPOILAGE_EXPOSURE[ship.commodity_class] * min(
        0.55, exposure["projected_delay_days"] / 25)
    hold_cost = _penalty(ship, base_late, hold_spoil)
    opts.append(dict(
        option_id="HOLD", kind="hold",
        label="Hold current routing",
        carrier=ship.carrier, mode=ship.mode,
        added_transit_days=0.0, incremental_cost_usd=0.0,
        late_days=round(base_late, 2), spoilage_prob=round(hold_spoil, 3),
        expected_penalty_usd=round(hold_cost, 0),
        reliability=CARRIERS[ship.carrier]["reliability"],
        rationale=(f"No action. Absorbs {exposure['projected_delay_days']}d of delay, "
                   f"{base_late:.1f}d past SLA."),
    ))

    # ---- 2. Physical reroutes --------------------------------------
    for name, via, add_days, cost_pct in BYPASS.get(choke, []):
        late = max(0.0, add_days - exposure["sla_slack_days"])
        # bypass removes the disruption delay but adds its own
        spoil = SPOILAGE_EXPOSURE[ship.commodity_class] * min(0.4, add_days / 40)
        inc = base_freight * cost_pct
        opts.append(dict(
            option_id=f"RR-{name[:3].upper()}", kind="reroute",
            label=f"Reroute via {name}",
            carrier=ship.carrier, mode=ship.mode,
            added_transit_days=add_days,
            incremental_cost_usd=round(inc, 0),
            late_days=round(late, 2), spoilage_prob=round(spoil, 3),
            expected_penalty_usd=round(_penalty(ship, late, spoil), 0),
            reliability=CARRIERS[ship.carrier]["reliability"],
            via=via,
            rationale=(f"Bypasses {NODES[choke][0]}; +{add_days}d transit, "
                       f"+{cost_pct*100:.0f}% freight."),
        ))

    # ---- 3. Carrier / mode shift -----------------------------------
    # Air is only physically sensible above a value-density floor: you do not
    # fly bulk automotive castings no matter what the penalty model says.
    value_density = ship.value_usd / max(1, ship.units)
    for cid, c in CARRIERS.items():
        if cid == ship.carrier:
            continue
        if cold and not c["reefer"]:
            continue
        if c["mode"] == "air" and value_density < 60:
            continue
        if c["mode"] == "road" and not ship.route[0].startswith("IN"):
            continue
        # mode speed factor vs. the disruption delay
        speedup = {"air": 0.92, "rail": 0.45, "road": 0.35, "ocean": 0.10}[c["mode"]]
        recovered = exposure["projected_delay_days"] * speedup
        late = max(0.0, base_late - recovered)
        inc = base_freight * (c["cost_idx"] - CARRIERS[ship.carrier]["cost_idx"])
        inc = max(0.0, inc)
        spoil = SPOILAGE_EXPOSURE[ship.commodity_class] * min(
            0.5, max(0.0, exposure["projected_delay_days"] - recovered) / 25)
        risk_premium = (1 - c["reliability"]) * ship.value_usd * 0.02
        opts.append(dict(
            option_id=f"MS-{cid}", kind="mode_shift",
            label=f"Shift to {c['name']} ({c['mode']})",
            carrier=cid, mode=c["mode"],
            added_transit_days=round(-recovered, 2),
            incremental_cost_usd=round(inc, 0),
            late_days=round(late, 2), spoilage_prob=round(spoil, 3),
            expected_penalty_usd=round(_penalty(ship, late, spoil) + risk_premium, 0),
            reliability=c["reliability"],
            rationale=(f"{c['mode'].title()} recovers {recovered:.1f}d of the "
                       f"{exposure['projected_delay_days']}d delay; "
                       f"carrier OTP {c['reliability']:.0%}."),
        ))

    # ---- Score & rank ----------------------------------------------
    for o in opts:
        o["total_expected_cost_usd"] = round(
            o["expected_penalty_usd"] + o["incremental_cost_usd"], 0)
    hold_total = next(o for o in opts if o["option_id"] == "HOLD")["total_expected_cost_usd"]
    for o in opts:
        o["savings_vs_hold_usd"] = round(hold_total - o["total_expected_cost_usd"], 0)
    opts.sort(key=lambda o: o["total_expected_cost_usd"])
    return opts


def recommend(shipments_by_id, exposures, now, top_n=25):
    """Recommend for the top-N exposed shipments."""
    recs = []
    seen = set()
    # One recommendation per shipment: the worst disruption it faces drives the call.
    ranked = [e for e in exposures if not (e["shipment_id"] in seen
                                           or seen.add(e["shipment_id"]))]
    # Air freight capacity is finite. Allocate it to the shipments where it buys
    # the most, then fall back to the best surface option for everyone else.
    air_teu_available = sum(c["capacity_teu"] for c in CARRIERS.values()
                            if c["mode"] == "air")
    staged = []
    for e in ranked[:top_n]:
        s = shipments_by_id[e["shipment_id"]]
        opts = options_for(s, e, now)
        staged.append((e, s, opts))
    # rank by how much air actually buys, so scarce capacity goes to the top
    def air_gain(t):
        _, _, opts = t
        air = [o for o in opts if o["mode"] == "air"]
        if not air:
            return -1
        surface = [o for o in opts if o["mode"] != "air"]
        return (min(o["total_expected_cost_usd"] for o in surface)
                - min(o["total_expected_cost_usd"] for o in air))
    for e, s, opts in sorted(staged, key=air_gain, reverse=True):
        teu = 2.0 if s.value_usd > 800_000 else 1.0
        if opts[0]["mode"] == "air":
            if air_teu_available >= teu:
                air_teu_available -= teu
            else:
                opts = [o for o in opts if o["mode"] != "air"]
                for o in opts:
                    o["rationale"] += " Air capacity exhausted this cycle."
        best = opts[0]
        recs.append(dict(
            shipment_id=s.shipment_id,
            customer=s.customer,
            commodity_class=s.commodity_class,
            value_usd=s.value_usd,
            disruption_id=e["disruption_id"],
            choke_node=e["choke_node"],
            exposure_score=e["exposure_score"],
            recommendation=best["label"],
            recommendation_kind=best["kind"],
            savings_vs_hold_usd=best["savings_vs_hold_usd"],
            incremental_cost_usd=best["incremental_cost_usd"],
            confidence=round(min(0.97, 0.55 + best["reliability"] * 0.4), 2),
            rationale=best["rationale"],
            options=opts[:4],
            air_capacity_constrained=bool(
                best["mode"] != "air"
                and any(o["mode"] == "air" for o in options_for(s, e, now))),
            requires_human_approval=bool(
                best["incremental_cost_usd"] > 25_000 or s.priority == "critical"),
        ))
    recs.sort(key=lambda r: -r["savings_vs_hold_usd"])
    return recs
