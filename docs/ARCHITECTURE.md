# SentinelChain — architecture

## 1. Shape of the system

```
            ┌──────────────────────────────────────────────────────┐
  feeds ──▶ │  ingest / normalise  (synthetic in demo, real in prod) │
            └──────────────────────────────────────────────────────┘
                                   │
            ┌──────────────────────┴───────────────────────────────┐
            │                  deterministic engines                │
            │  impact.py   reroute.py   fleet.py   coldchain.py     │
            └──────────────────────┬───────────────────────────────┘
                                   │  pure functions, no I/O, no model calls
            ┌──────────────────────┴───────────────────────────────┐
            │  agent layer — tool registry, routing, guardrails      │
            │  agent.py  ·  PlatformAdapter  ·  approval thresholds  │
            └──────────────────────┬───────────────────────────────┘
                                   │
            ┌──────────────────────┴───────────────────────────────┐
            │  surfaces — dashboard, CLI, drafted notices           │
            └──────────────────────────────────────────────────────┘
```

The load-bearing decision is the boundary between the engines and the agent.
Engines are pure: same inputs, same outputs, no network, no model. The agent
chooses *which* engine to call and narrates the result. It never computes.

Three things follow from that split:

1. **Auditability.** A regulator asking "how did you classify this batch?" gets
   a formula and a set of rules, not a model transcript.
2. **Testability.** Engines are unit-testable without mocking a model.
3. **Portability.** Swapping the agent runtime is an adapter change, not a
   rewrite.

---

## 2. Data contracts

Each feed is normalised into one of four records. Production sources listed
against each.

### Shipment
```
shipment_id, customer, commodity_class, value_usd, units, priority,
route[node...], carrier, mode, leg_index, departed, eta, sla_deadline,
temp_min, temp_max, stability_budget_min
```
*Source:* TMS export, or EDI 214 / EDIFACT IFTSTA status messages keyed on
shipment reference. `leg_index` is derived from the most recent status event.

### Disruption
```
disruption_id, kind, headline, nodes[], severity(0-1), started,
expected_clear, added_transit_days, source
```
*Source:* carrier advisories, port authority bulletins, weather APIs, maritime
advisories. `severity` and `added_transit_days` come from the advisory where
stated and from a per-kind prior where not.

### Asset
```
asset_id, kind, location, status, idle_since, capacity_teu,
reefer_capable, day_rate_usd
```
*Source:* telematics feed keyed on asset ID; `day_rate_usd` from the finance
system's carrying-cost table.

### Sensor reading
```
shipment_id, leg, ts, temp_c, humidity, door_open
```
*Source:* reefer IoT loggers over MQTT, or a logger vendor's batch API.
Sampling is assumed regular; the excursion integrator takes the interval as a
parameter (`sample_min`, default 30).

---

## 3. Engine notes

### 3.1 Exposure (`impact.py`)

Exposure is set membership, not geography: a shipment is exposed when the
intersection of its remaining nodes and the disruption's node set is non-empty.
Remaining nodes deliberately include the node the shipment is currently
departing — a strike at the origin of the active leg still holds the box, the
paperwork and the feeder connection.

The score is a weighted blend, kept linear on purpose so an operator can be
told exactly why row 3 outranks row 7:

| Signal | Weight | Notes |
|---|---|---|
| Value at risk | 30% | capped at $1.5M so one mega-shipment can't dominate |
| Cargo fragility | 22% | class constant: vaccine 1.00 → automotive 0.20 |
| SLA breach depth | 20% | projected delay minus existing SLA slack |
| Disruption severity | 16% | from the advisory |
| Time-to-choke × priority | 12% | urgency decays as 1.6 / (1 + days) |

Time-to-choke is interpolated linearly across remaining legs. That is crude and
is the first thing to replace with real per-leg transit times.

### 3.2 Re-route (`reroute.py`)

Option families: `hold`, `reroute` (physical bypass of the choke node),
`mode_shift` (different carrier and/or mode).

Every option is priced on one number:

```
total_expected_cost = SLA_penalty + spoilage_cost + incremental_freight
SLA_penalty         = value × rate(priority) × late_days
spoilage_cost       = value × P(spoil | class, exposure_days)
```

`hold` is always in the candidate set, so the ranking answers "is acting worth
it?" rather than "which action?". `savings_vs_hold_usd` is reported on every
option.

Two constraints stop the model from simply flying everything:

- **Value-density floor.** Air is filtered out below $60/unit — you don't fly
  bulk castings regardless of what the penalty model says.
- **Finite air capacity.** A shared TEU pool is allocated to the shipments where
  air buys the most (surface-best cost minus air-best cost), and shipments that
  miss out fall back to their best surface option with the reason recorded in
  `air_capacity_constrained`.

### 3.3 Fleet (`fleet.py`)

Idle thresholds are per asset kind, because idleness means different things:

| Kind | Threshold | Day rate |
|---|---|---|
| reefer truck | 0.75 d | $520 |
| truck | 1.0 d | $340 |
| vessel slot | 1.5 d | $2,400 |
| reefer container | 2.0 d | $210 |
| dry container | 4.0 d | $90 |

Demand is generated, not configured: each re-route recommendation raises a
signal at the node it needs capacity at, and baseline lane throughput raises a
smaller one everywhere else. Matching is greedy over demand sorted by value,
choosing the asset that maximises `value_released − repositioning_cost`, with a
4,500 km reposition radius and a reefer-serves-dry-but-not-vice-versa rule.

Greedy is a deliberate choice for a demo: an LP or min-cost-flow would score
marginally better and be much harder to explain in a two-minute answer.

### 3.4 Cold chain (`coldchain.py`)

Mean Kinetic Temperature, Haynes form with the ICH-conventional activation
energy ΔH = 83.144 kJ/mol:

```
MKT = (ΔH/R) / ( −ln( Σ exp(−ΔH / (R·Tᵢ)) / n ) )
```

MKT answers a different question from a threshold alarm. A threshold alarm asks
"did it ever go out of range?" MKT asks "how much degradation did the whole
profile actually cause?" A short door-open blip and a nine-hour reefer failure
have the same answer to the first question and very different answers to the
second.

Classification uses three measurements — cumulative time-out-of-range as a
fraction of the product's stability budget, peak deviation from the label range,
and the longest single window — plus MKT itself:

| Band | Trigger | Disposition |
|---|---|---|
| GREEN | no time out of range | auto-release, log to batch record |
| AMBER | ≤15% budget, ≤2°C peak deviation, ≤60 min window | release with deviation note, QA sign-off in 24h |
| ORANGE | 15–60% budget, or 2–6°C deviation, or >60 min window, or MKT outside label | quarantine on arrival, stability assessment |
| RED | >60% budget, or >10°C deviation, or >6°C deviation held ≥2h, or window >6h | presumed non-conforming, recall workflow |

Two refinements that matter in practice:

- **MKT override.** If MKT itself falls outside the label range, the profile as
  a whole is non-conforming, not just a spike — that alone escalates to ORANGE.
- **Door-correlation.** Windows that align with door-open events are handling,
  not equipment failure. This is recorded in the reasons and holds severity at
  ORANGE pending reefer diagnostics rather than escalating.

Vaccines carry an extra rule: held more than 2h at >4°C above label, VVM stage
advancement is assumed (WHO PQS E006) and the band goes RED.

Every classification returns `reasons[]`, the regulatory hook, the disposition,
and `hours_to_delivery` — because a breach caught with the window open is a
decision, and one caught at the door is only paperwork.

---

## 4. Agent layer

### Tool registry

Six tools, written as JSON-schema function specs in `agent.TOOLS`:

| Tool | Returns |
|---|---|
| `assess_disruption_impact` | ranked exposure records |
| `recommend_reroute` | scored options for one shipment |
| `find_idle_assets` | idle assets with carrying cost |
| `propose_redeployment` | matched redeployment plan |
| `analyse_cold_chain` | MKT, TOR, severity, disposition |
| `draft_stakeholder_notice` | drafted text, never sent |

### The seam

```python
@dataclass
class PlatformAdapter:
    call_model: Callable[[str, list, list], dict] | None = None
```

`call_model(system, messages, tools)` returns either `{"text": ...}` or
`{"tool_call": {"name", "arguments"}}`. That is the whole contract. The demo
ships an `OfflineRouter` implementing deterministic keyword intent routing so
the system runs with no network; replacing it with a real tool-calling model
changes nothing else.

### Guardrails

Enforced in `needs_approval()`, not in the system prompt, because a prompt can
be argued out of a rule:

```python
APPROVAL_RULES = {
    "incremental_cost_usd": 25_000,
    "always_approve_classes": ["vaccine_2_8", "biologic_frozen"],
    "always_approve_severity": ["RED"],
}
```

The system prompt adds behavioural rules on top — never compute, always quote
the dollar delta, always name the regulatory hook, never fill a gap when a tool
returns nothing.

---

## 5. What to build next

1. Replace linear leg interpolation with per-leg transit estimates from
   historical AIS or carrier schedules.
2. Book capacity rather than assume it: query carrier space APIs before a
   mode-shift option is ranked.
3. Per-SKU stability budgets from the product master, replacing class defaults.
4. Min-cost-flow for fleet matching once the explanation surface can carry it.
5. Write-back: push an approved re-route to the TMS as a booking amendment, and
   an approved disposition to the QMS as a deviation record.
6. Learn the priors — disruption `added_transit_days` and spoilage
   probabilities should come from outcome history, not constants.
