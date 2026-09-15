"""
coldchain.py — detect temperature excursions from IoT logs and classify them
into a regulatory severity band BEFORE the shipment is delivered.

Why this is not just "temp > max":
  * A 20-minute door-open blip is not a 9-hour reefer failure, but a naive
    threshold alarm treats them identically and ops learns to ignore alarms.
  * Regulators do not judge a peak, they judge cumulative thermal insult.
    So we compute Mean Kinetic Temperature (MKT) alongside cumulative
    time-out-of-range (TOR) and consume a product-specific stability budget.

Metrics computed per shipment:
  MKT      Mean Kinetic Temperature (Haynes 1971, ICH Q1A) — the single
           isothermal temperature that would cause the same degradation as
           the observed variable profile.
  TOR      cumulative minutes outside the label range.
  Budget   % of the product's out-of-range stability allowance consumed.
  Severity GREEN / AMBER / ORANGE / RED with a named regulatory hook and a
           concrete disposition action.
"""
from __future__ import annotations

import math
from datetime import datetime

DELTA_H = 83_144.0     # J/mol, ICH-conventional activation energy
R_GAS = 8.314          # J/(mol·K)

SEVERITY_ORDER = ["GREEN", "AMBER", "ORANGE", "RED"]

REG_HOOKS = {
    "vaccine_2_8": "WHO TRS 961 Annex 9 §5; PQS E006 VVM staging",
    "biologic_frozen": "ICH Q5C; EU GDP 2013/C 343/01 §9.2",
    "perishable_food": "FSMA 21 CFR 1.908 Sanitary Transport",
    "pharma_ambient": "ICH Q1A(R2) long-term storage",
}

DISPOSITION = {
    "GREEN": "Auto-release. Log profile to the batch record.",
    "AMBER": "Release with deviation note. QA sign-off required within 24h.",
    "ORANGE": "Quarantine on arrival. Stability assessment before release.",
    "RED": "Presumed non-conforming. Do not distribute. Trigger recall workflow "
           "and insurance claim.",
}


def mean_kinetic_temperature(temps_c):
    """Haynes MKT over a uniformly-sampled series."""
    if not temps_c:
        return None
    n = len(temps_c)
    acc = 0.0
    for t in temps_c:
        tk = t + 273.15
        if tk <= 0:
            continue
        acc += math.exp(-DELTA_H / (R_GAS * tk))
    if acc <= 0:
        return None
    mkt_k = (DELTA_H / R_GAS) / (-math.log(acc / n))
    return round(mkt_k - 273.15, 2)


def _excursion_windows(series, tmin, tmax, sample_min=30):
    """Contiguous runs outside the label range."""
    windows, cur = [], None
    for p in series:
        out = p["temp_c"] > tmax or p["temp_c"] < tmin
        if out and cur is None:
            cur = dict(start=p["ts"], end=p["ts"], peak=p["temp_c"],
                       minutes=sample_min, direction="high" if p["temp_c"] > tmax else "low",
                       door_events=p["door_open"], leg=p["leg"])
        elif out:
            cur["end"] = p["ts"]
            cur["minutes"] += sample_min
            cur["peak"] = max(cur["peak"], p["temp_c"]) if cur["direction"] == "high" \
                else min(cur["peak"], p["temp_c"])
            cur["door_events"] += p["door_open"]
        elif cur is not None:
            windows.append(cur)
            cur = None
    if cur is not None:
        windows.append(cur)
    return windows


def classify(ship, windows, mkt, tor_minutes):
    """Severity band + why. Rules are explicit and auditable."""
    budget = ship.stability_budget_min
    pct = tor_minutes / budget if budget else 0.0
    peak_dev = 0.0
    for w in windows:
        dev = (w["peak"] - ship.temp_max) if w["direction"] == "high" \
            else (ship.temp_min - w["peak"])
        peak_dev = max(peak_dev, dev)
    longest = max((w["minutes"] for w in windows), default=0)
    mkt_out = mkt is not None and (mkt > ship.temp_max or mkt < ship.temp_min)

    reasons = []
    sev = "GREEN"

    def raise_to(level, why):
        nonlocal sev
        if SEVERITY_ORDER.index(level) > SEVERITY_ORDER.index(sev):
            sev = level
        reasons.append(why)

    if tor_minutes == 0:
        return "GREEN", ["Profile fully within label range for the monitored window."], 0.0

    if pct <= 0.15 and peak_dev <= 2.0 and longest <= 60:
        raise_to("AMBER", f"Minor excursion: {tor_minutes} min out of range "
                          f"({pct:.0%} of stability budget), peak deviation "
                          f"{peak_dev:.1f}°C.")
    if 0.15 < pct <= 0.60 or (2.0 < peak_dev <= 6.0) or longest > 60:
        raise_to("ORANGE", f"Significant thermal insult: {pct:.0%} of stability "
                           f"budget consumed, longest single window {longest} min.")
    if (pct > 0.60 or longest > 360 or peak_dev > 10.0
            or (peak_dev > 6.0 and longest >= 120)):
        raise_to("RED", f"Budget exceeded or severe deviation: {pct:.0%} of stability "
                        f"budget consumed, peak deviation {peak_dev:.1f}°C, longest "
                        f"window {longest} min.")
    if mkt_out:
        raise_to("ORANGE", f"MKT of {mkt}°C sits outside the {ship.temp_min}–"
                           f"{ship.temp_max}°C label range — the whole profile, "
                           f"not one spike, is non-conforming.")
    if ship.commodity_class == "vaccine_2_8" and peak_dev > 4.0 and longest > 120:
        raise_to("RED", "Vaccine held >2h at >4°C above label — VVM stage "
                        "advancement assumed under WHO PQS E006.")
    door_only = all(w["door_events"] >= max(1, w["minutes"] // 60) and w["minutes"] <= 60
                    for w in windows)
    if door_only and sev == "ORANGE":
        reasons.append("All windows correlate with door-open events — handling, "
                       "not equipment failure. Severity held at ORANGE pending "
                       "reefer diagnostics.")
    return sev, reasons, round(pct, 3)


def analyse(shipments_by_id, iot_logs, now):
    results = []
    for sid, series in iot_logs.items():
        s = shipments_by_id[sid]
        temps = [p["temp_c"] for p in series]
        mkt = mean_kinetic_temperature(temps)
        windows = _excursion_windows(series, s.temp_min, s.temp_max)
        tor = sum(w["minutes"] for w in windows)
        sev, reasons, pct = classify(s, windows, mkt, tor)
        eta = datetime.fromisoformat(s.eta)
        hours_to_delivery = round((eta - now).total_seconds() / 3600, 1)
        results.append(dict(
            shipment_id=sid,
            customer=s.customer,
            commodity_class=s.commodity_class,
            label_range=f"{s.temp_min}–{s.temp_max}°C",
            value_usd=s.value_usd,
            units=s.units,
            mkt_c=mkt,
            excursion_count=len(windows),
            tor_minutes=tor,
            stability_budget_min=s.stability_budget_min,
            budget_consumed_pct=pct,
            peak_temp_c=round(max(temps), 2),
            min_temp_c=round(min(temps), 2),
            severity=sev,
            reasons=reasons,
            regulatory_hook=REG_HOOKS.get(s.commodity_class, "Internal SOP"),
            disposition=DISPOSITION[sev],
            hours_to_delivery=hours_to_delivery,
            caught_before_delivery=hours_to_delivery > 0,
            windows=windows[:5],
            value_protected_usd=s.value_usd if sev in ("ORANGE", "RED") and hours_to_delivery > 0 else 0,
        ))
    order = {k: i for i, k in enumerate(SEVERITY_ORDER)}
    results.sort(key=lambda r: (order[r["severity"]], r["value_usd"]), reverse=True)
    return results


def summary(results):
    counts = {k: 0 for k in SEVERITY_ORDER}
    for r in results:
        counts[r["severity"]] += 1
    flagged = [r for r in results if r["severity"] in ("ORANGE", "RED")]
    return dict(
        monitored=len(results),
        counts=counts,
        flagged=len(flagged),
        flagged_value_usd=sum(r["value_usd"] for r in flagged),
        caught_pre_delivery=sum(1 for r in flagged if r["caught_before_delivery"]),
        value_protected_usd=sum(r["value_protected_usd"] for r in results),
        false_alarm_suppression=round(
            1 - (len(flagged) / max(1, sum(1 for r in results if r["excursion_count"] > 0))), 3),
    )
