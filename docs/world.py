"""
world.py — synthetic but realistic operating picture for SentinelChain.

Generates: network nodes, lanes, carriers, shipments in flight, active
disruptions, fleet assets, and cold-chain IoT sensor logs.

Deterministic (seeded) so the demo is reproducible in front of judges.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

SEED = 20260915
NOW = datetime(2026, 9, 15, 6, 0)

# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
NODES = {
    # code: (name, country, lat, lon, kind)
    "INMUN": ("Mundra Port", "IN", 22.839, 69.728, "seaport"),
    "INNSA": ("Nhava Sheva (JNPT)", "IN", 18.949, 72.951, "seaport"),
    "INBHV": ("Bhavnagar DC", "IN", 21.764, 72.152, "dc"),
    "INAMD": ("Ahmedabad Hub", "IN", 23.022, 72.571, "hub"),
    "INDEL": ("Delhi NCR Hub", "IN", 28.614, 77.209, "hub"),
    "INBLR": ("Bengaluru Cold DC", "IN", 12.972, 77.594, "cold_dc"),
    "AEJEA": ("Jebel Ali", "AE", 25.011, 55.061, "seaport"),
    "SGSIN": ("Singapore", "SG", 1.264, 103.822, "seaport"),
    "CNSHA": ("Shanghai", "CN", 31.230, 121.474, "seaport"),
    "CNSZX": ("Shenzhen/Yantian", "CN", 22.543, 114.058, "seaport"),
    "NLRTM": ("Rotterdam", "NL", 51.949, 4.140, "seaport"),
    "DEHAM": ("Hamburg", "DE", 53.541, 9.984, "seaport"),
    "USLAX": ("Los Angeles", "US", 33.740, -118.264, "seaport"),
    "USORD": ("Chicago RDC", "US", 41.878, -87.630, "dc"),
    "USEWR": ("Newark", "US", 40.688, -74.175, "seaport"),
    "EGSUZ": ("Suez Canal", "EG", 30.028, 32.551, "chokepoint"),
    "PABLB": ("Panama Canal", "PA", 9.080, -79.680, "chokepoint"),
    "ZADUR": ("Durban", "ZA", -29.868, 31.023, "seaport"),
    "GBFXT": ("Felixstowe", "GB", 51.955, 1.351, "seaport"),
    "KEMBA": ("Mombasa", "KE", -4.043, 39.668, "seaport"),
}


def haversine_km(a: str, b: str) -> float:
    la1, lo1 = NODES[a][2], NODES[a][3]
    la2, lo2 = NODES[b][2], NODES[b][3]
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(h)), 1)


CARRIERS = {
    "MAERSK-OC": dict(name="Maersk Ocean", mode="ocean", reliability=0.91,
                      cost_idx=1.00, reefer=True, capacity_teu=180),
    "MSC-OC": dict(name="MSC Ocean", mode="ocean", reliability=0.86,
                   cost_idx=0.92, reefer=True, capacity_teu=220),
    "CMA-OC": dict(name="CMA CGM", mode="ocean", reliability=0.88,
                   cost_idx=0.97, reefer=True, capacity_teu=150),
    "QR-AIR": dict(name="Qatar Air Cargo", mode="air", reliability=0.96,
                   cost_idx=4.30, reefer=True, capacity_teu=18),
    "EK-AIR": dict(name="Emirates SkyCargo", mode="air", reliability=0.95,
                   cost_idx=4.05, reefer=True, capacity_teu=22),
    "DBS-RAIL": dict(name="DB Schenker Rail", mode="rail", reliability=0.89,
                     cost_idx=1.45, reefer=True, capacity_teu=90),
    "BLR-ROAD": dict(name="BlueDart Road", mode="road", reliability=0.93,
                     cost_idx=1.30, reefer=True, capacity_teu=12),
    "GATI-ROAD": dict(name="Gati Surface", mode="road", reliability=0.84,
                      cost_idx=0.95, reefer=False, capacity_teu=14),
}

COMMODITIES = {
    # class: (temp_min, temp_max, stability_budget_min, value_low, value_high)
    "vaccine_2_8": (2.0, 8.0, 720, 380_000, 1_450_000),
    "biologic_frozen": (-25.0, -15.0, 240, 600_000, 2_100_000),
    "pharma_ambient": (15.0, 25.0, 2880, 90_000, 400_000),
    "perishable_food": (0.0, 4.0, 480, 40_000, 180_000),
    "electronics": (-40.0, 60.0, 99999, 150_000, 900_000),
    "automotive": (-40.0, 60.0, 99999, 60_000, 500_000),
}

LANES = [
    ("CNSHA", "NLRTM", ["CNSHA", "SGSIN", "EGSUZ", "NLRTM"], 31),
    ("CNSZX", "USLAX", ["CNSZX", "USLAX"], 18),
    ("INMUN", "NLRTM", ["INMUN", "AEJEA", "EGSUZ", "NLRTM"], 22),
    ("INNSA", "DEHAM", ["INNSA", "AEJEA", "EGSUZ", "DEHAM"], 24),
    ("SGSIN", "USEWR", ["SGSIN", "EGSUZ", "USEWR"], 34),
    ("INBHV", "AEJEA", ["INBHV", "INMUN", "AEJEA"], 6),
    ("INAMD", "INBLR", ["INAMD", "INBHV", "INBLR"], 3),
    ("CNSHA", "USORD", ["CNSHA", "USLAX", "USORD"], 24),
    ("INDEL", "GBFXT", ["INDEL", "INNSA", "EGSUZ", "GBFXT"], 27),
    ("KEMBA", "NLRTM", ["KEMBA", "EGSUZ", "NLRTM"], 20),
    ("ZADUR", "NLRTM", ["ZADUR", "NLRTM"], 23),
    ("INMUN", "SGSIN", ["INMUN", "SGSIN"], 11),
]

CUSTOMERS = ["GaviHealth", "NovaBio", "Serum Global", "AgriFresh", "VoltCell",
             "Northwind Auto", "MedEx Pharma", "Helios Retail", "TataChem"]


@dataclass
class Shipment:
    shipment_id: str
    customer: str
    commodity_class: str
    value_usd: int
    route: list
    carrier: str
    mode: str
    leg_index: int
    departed: str
    eta: str
    sla_deadline: str
    temp_min: float
    temp_max: float
    stability_budget_min: int
    units: int
    priority: str

    @property
    def current_leg(self):
        return (self.route[self.leg_index], self.route[self.leg_index + 1])


@dataclass
class Disruption:
    disruption_id: str
    kind: str
    headline: str
    nodes: list
    severity: float          # 0-1
    started: str
    expected_clear: str
    added_transit_days: float
    source: str


@dataclass
class Asset:
    asset_id: str
    kind: str                # truck | reefer_truck | container | reefer_container | vessel_slot
    location: str
    status: str              # idle | in_transit | maintenance
    idle_since: str | None
    capacity_teu: float
    reefer_capable: bool
    day_rate_usd: int


def build_world():
    rng = random.Random(SEED)

    # ---------------- Disruptions (the live picture) ----------------
    disruptions = [
        Disruption("DSR-1041", "geopolitical",
                   "Red Sea transit advisory — Suez routings diverting via Cape of Good Hope",
                   ["EGSUZ"], 0.88, (NOW - timedelta(days=4)).isoformat(),
                   (NOW + timedelta(days=21)).isoformat(), 11.0, "IMO/UKMTO advisory"),
        Disruption("DSR-1042", "port_strike",
                   "Rotterdam terminal labour action — gate ops at 35% capacity",
                   ["NLRTM"], 0.72, (NOW - timedelta(days=1)).isoformat(),
                   (NOW + timedelta(days=6)).isoformat(), 4.5, "Port authority notice"),
        Disruption("DSR-1043", "weather",
                   "Typhoon Ampil — Shanghai/Yantian berth closures",
                   ["CNSHA", "CNSZX"], 0.65, (NOW - timedelta(hours=18)).isoformat(),
                   (NOW + timedelta(days=3)).isoformat(), 2.5, "JTWC track + terminal bulletin"),
        Disruption("DSR-1044", "congestion",
                   "Jebel Ali yard congestion — 38h average dwell",
                   ["AEJEA"], 0.41, (NOW - timedelta(days=6)).isoformat(),
                   (NOW + timedelta(days=4)).isoformat(), 1.6, "Carrier yard feed"),
    ]

    # ---------------- Shipments ----------------
    shipments = []
    for i in range(140):
        o, d, route, base_days = rng.choice(LANES)
        cls = rng.choices(
            list(COMMODITIES),
            weights=[12, 6, 14, 16, 26, 26], k=1)[0]
        tmin, tmax, budget, vlo, vhi = COMMODITIES[cls]
        cold = cls in ("vaccine_2_8", "biologic_frozen", "perishable_food")
        carrier = rng.choice([c for c, v in CARRIERS.items()
                              if (v["reefer"] or not cold)
                              and (v["mode"] == "road") == (len(route) <= 3 and o.startswith("IN"))])
        leg_index = rng.randrange(0, len(route) - 1)
        departed = NOW - timedelta(days=rng.uniform(1, base_days * 0.7))
        eta = departed + timedelta(days=base_days)
        sla = eta + timedelta(days=rng.choice([0, 1, 1, 2, 3]))
        value = rng.randrange(vlo, vhi, 1000)
        shipments.append(Shipment(
            shipment_id=f"SHP-{80000+i}",
            customer=rng.choice(CUSTOMERS),
            commodity_class=cls,
            value_usd=value,
            route=route,
            carrier=carrier,
            mode=CARRIERS[carrier]["mode"],
            leg_index=leg_index,
            departed=departed.isoformat(timespec="minutes"),
            eta=eta.isoformat(timespec="minutes"),
            sla_deadline=sla.isoformat(timespec="minutes"),
            temp_min=tmin, temp_max=tmax,
            stability_budget_min=budget,
            units=rng.randrange(200, 9000, 50),
            priority=rng.choices(["critical", "high", "standard"],
                                 weights=[1, 3, 6])[0],
        ))

    # ---------------- Fleet ----------------
    assets = []
    locs = list(NODES)
    for i in range(96):
        kind = rng.choices(
            ["truck", "reefer_truck", "container", "reefer_container", "vessel_slot"],
            weights=[26, 18, 24, 20, 12])[0]
        status = rng.choices(["idle", "in_transit", "maintenance"],
                             weights=[38, 55, 7])[0]
        idle_days = rng.uniform(0.3, 14.0)
        assets.append(Asset(
            asset_id=f"AST-{2200+i}",
            kind=kind,
            location=rng.choice(locs),
            status=status,
            idle_since=(NOW - timedelta(days=idle_days)).isoformat(timespec="minutes")
            if status == "idle" else None,
            capacity_teu={"truck": 2, "reefer_truck": 2, "container": 1,
                          "reefer_container": 1, "vessel_slot": 40}[kind],
            reefer_capable=kind in ("reefer_truck", "reefer_container"),
            day_rate_usd={"truck": 340, "reefer_truck": 520, "container": 90,
                          "reefer_container": 210, "vessel_slot": 2400}[kind],
        ))

    # ---------------- Cold-chain IoT logs ----------------
    # One reading every 30 min for the last 72h, for every cold shipment.
    logs = {}
    cold_ships = [s for s in shipments
                  if s.commodity_class in ("vaccine_2_8", "biologic_frozen", "perishable_food")]
    # Deliberately plant excursions in ~30% of cold shipments, of varying severity.
    planted = rng.sample(cold_ships, k=int(len(cold_ships) * 0.32))
    plant_ids = {s.shipment_id for s in planted}

    for s in cold_ships:
        mid = (s.temp_min + s.temp_max) / 2
        series = []
        t = NOW - timedelta(hours=72)
        # excursion window
        exc = None
        if s.shipment_id in plant_ids:
            start_h = rng.uniform(4, 60)
            dur_h = rng.choices([0.5, 1.0, 2.0, 4.0, 9.0, 18.0],
                                weights=[30, 24, 18, 14, 9, 5])[0]
            magnitude = rng.choices([rng.uniform(0.8, 2.0), rng.uniform(2.0, 5.5),
                                     rng.uniform(5.5, 11.0)], weights=[42, 38, 20])[0]
            exc = (start_h, start_h + dur_h, magnitude)
        for step in range(145):
            hrs = step * 0.5
            temp = mid + rng.gauss(0, 0.35)
            door = 0
            if exc and exc[0] <= hrs <= exc[1]:
                ramp = min(1.0, (hrs - exc[0]) / 0.75)
                temp = s.temp_max + exc[2] * ramp + rng.gauss(0, 0.3)
                door = 1 if rng.random() < 0.25 else 0
            series.append(dict(
                ts=(t + timedelta(hours=hrs)).isoformat(timespec="minutes"),
                temp_c=round(temp, 2),
                humidity=round(rng.uniform(38, 62), 1),
                door_open=door,
                leg=min(s.leg_index, len(s.route) - 2),
            ))
        logs[s.shipment_id] = series

    return dict(shipments=shipments, disruptions=disruptions,
                assets=assets, iot=logs, now=NOW)


def to_dicts(objs):
    return [asdict(o) for o in objs]
