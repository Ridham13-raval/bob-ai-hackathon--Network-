# SentinelChain — live demo script

Target: 4–5 minutes talking, 2–3 minutes live clicking, under the numbers on
the current seeded run ($9.99M defended, 140 shipments, 4 disruptions).
Re-run `python3 run_demo.py && python3 build_dashboard.py` right before you
present — the dataset is time-seeded off "now," so figures stay internally
consistent but will drift slightly by wall-clock date.

Open two things before you start talking: the deck (`SentinelChain_Pitch.pptx`,
or present from the PDF) and `out/sentinelchain_dashboard.html` in a second
browser tab, already loaded so there's no load-time dead air.

---

## 0. Before anyone's watching

```bash
cd sentinelchain
python3 run_demo.py               # confirm it still runs clean, note the KPI block
python3 build_dashboard.py
open out/sentinelchain_dashboard.html
```

Scan the console output once — the top disruption and top reroute recommendation
sometimes shift with the seed/date. Know the current top line of each before
you're asked a question about it.

---

## 1. Open (slide 1) — 20 seconds

Don't read the slide. Say it:

> "SentinelChain is an agent that turns four disconnected feeds — disruption
> advisories, shipment status, fleet telematics, cold-chain sensors — into one
> ranked decision queue. On tonight's seeded run it defends just under ten
> million dollars of cargo value. I'll show you where every dollar of that
> comes from, and then I'll ask it a question live."

Move to slide 2 immediately — don't linger on the big number, it lands harder
at the close.

---

## 2. The problem (slide 2) — 30 seconds

Point, don't read:

> "Three things are happening at once and nobody can see all three. A Suez
> advisory is one headline — underneath it are dozens of shipments, a chunk of
> them temperature-controlled. Meanwhile the fleet that could absorb the delay
> is sitting idle somewhere else, burning carrying cost. And if a reefer fails,
> today you find out at the delivery door, when it's too late to do anything
> but write off the batch."

---

## 3. How it works (slide 3) — 30 seconds

> "One agent, four deterministic engines. The agent's only job is picking
> which tool to call — it never does arithmetic itself. That's not a style
> choice, it's the whole trust story, and I'll come back to it."

---

## 4–7. The four engines (slides 4–7) — ~90 seconds total, ~20s each

Keep pace brisk here — judges have seen scoring formulas before. Land one
concrete number per engine and move on.

- **Exposure (4):** "Score blends value, fragility, SLA breach, severity, and
  how soon it hits the blocked node. That's 109 of our 140 shipments — a raw
  list is useless, which is why the score exists."
- **Re-route (5):** *"Holding" is always scored, so the model has to beat doing
  nothing.* Point at the air-capacity callout: "Air freight capacity is finite
  — we allocate it to the shipments where it buys the most, and ten shipments
  tonight lost that slot and fell back to a surface option. That constraint is
  what stops this from just flying everything."
- **Fleet (6):** "The re-route engine creates the demand — a box diverted
  through Durban needs a reefer at Durban — and the fleet engine fills it with
  metal that was already paid for. 57% to 85% utilisation, this run."
- **Cold chain (7):** This is the one to slow down for. "A threshold alarm
  treats a twenty-minute door-open blip and a nine-hour reefer failure
  identically, so operators learn to ignore it. We compute Mean Kinetic
  Temperature — the single isothermal temperature that would degrade the
  product as much as the real profile did. That's the number a regulator asks
  for. Ten of ten flagged shipments tonight were caught while still in
  transit, with the intervention window still open."

---

## 5. Switch to the live dashboard (slide 8, then alt-tab) — 90 seconds

> "Let me show you the same thing live."

Alt-tab to the dashboard. Let the ribbon chart breathe for a second before
talking over it.

1. **Point at the ribbon.** "Every exposed shipment, plotted by how many days
   until it hits its blocked node and how urgent it is. Left of the dashed
   line needs a decision this week."
2. **Click an incident card** in the left rail (Red Sea or Rotterdam — whichever
   has the biggest value-at-risk bar). Watch the ribbon and table filter live.
   "Filtering to one incident — same view, scoped."
3. **Click "Decisions" tab, click a row** to expand it. "Every option, ranked,
   with 'do nothing' sitting right there as the baseline it has to beat."
4. **Type in the ask box** — use exactly one of these, picked for reliability:
   - `which vaccine shipments have a temperature problem?`
   - `any idle containers I can redeploy?`
   - `what should I do about the Suez diversion?`

   Hit Ask. Read the routed tool name out loud: *"agent → analyse_cold_chain()
   — it picked the tool, and every number in the answer is quoted straight
   from the engine."*
5. **Click "Cold chain" tab, click the top RED row** to expand the trace chart.
   "That's the actual sensor profile. Flat, spikes for nine hours, flat again
   — MKT and time-out-of-range catch what a simple max-temp alarm would flag
   identically to a five-minute door-open."

If a live query stalls or looks wrong under pressure, don't debug on stage —
say "let me show you the same answer from the CLI" and fall back to a
pre-run terminal with `python3 run_demo.py --ask "..."` already in scrollback.

---

## 6. Trust (slide 9) — 25 seconds

> "None of what you just saw is the model guessing. Every number came from
> tested Python. Anything over $25,000, anything touching a vaccine or a
> frozen biologic, every RED classification — those are proposals, not
> actions. Tonight, 11 of 25 recommendations were held for human sign-off."

---

## 7. Integration (slide 10) — 20 seconds

> "This is built to drop onto Bob, or anything else that does tool calling.
> Six tools, JSON-schema specs, one adapter method to implement. The engines,
> the guardrails, the dashboard — none of that changes."

(If asked what Bob is and you're not briefed yet: "That's a detail I'm
finalizing with the team — the adapter is deliberately runtime-agnostic so
it's a non-issue either way.")

---

## 8. Honesty (slide 11) — 20 seconds

> "Quickly — what's real and what isn't. All four engines run end to end in
> front of you tonight, on tested code. What's not real: this is a seeded
> synthetic dataset, not live carrier feeds, and we're not booking carrier
> space, just pricing against a quoted index. Nothing in this deck is a
> mock-up of something that doesn't run."

---

## 9. Close (slide 12) — 20 seconds

> "One run, one operator, four decisions that used to take a day: $3.42
> million from re-routing, $6.17 million in cold cargo caught in transit,
> $401 thousand of fleet capacity recovered. Just under ten million dollars,
> defended, in one pass."

Stop talking. Let the number sit. Take questions.

---

## Anticipated questions

**"Is the LLM making up the exposure score / MKT / savings numbers?"**
No — walk to slide 9 or the code: every number is a return value from
`engine/impact.py`, `reroute.py`, `fleet.py`, or `coldchain.py`. The agent
only picks which function to call.

**"What happens if two disruptions hit the same shipment?"**
The exposure table dedupes to the worst one (`impact.py` sorts by score, the
recommender takes the first hit per shipment). Mention it's a deliberate
choice — one clear ask beats two competing ones.

**"How would this get real data on day one?"** — point to the "Real data, day
one" box on slide 10: TMS/EDI 214 for shipments, carrier/port bulletins and
weather APIs for disruptions, telematics for fleet, MQTT reefer loggers for
cold chain.

**"Why greedy matching instead of an optimizer for fleet?"**
Deliberate: a solved optimum scores marginally better and can't be explained
in one line to an ops manager. Greedy-on-net-benefit is fully auditable.

**"What's not finished?"** — read straight from slide 11's right column. Don't
soften it; the honesty lands better flat.

---

## Timing budget

| Section | Time |
|---|---|
| Open + problem | 50s |
| How it works + 4 engines | 2:00 |
| Live dashboard | 1:30 |
| Trust + integration + honesty | 1:05 |
| Close | 20s |
| **Total** | **~5:45**, trims to ~4:30 by shortening engine slides to one line each |

If time is cut to 3 minutes: skip slides 4–7 individually, say the one-line
version of "four engines" from slide 3, go straight to the live dashboard,
then close on slide 12's number.
