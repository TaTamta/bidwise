# BidWise — AI agent pipeline for US car auction buying (Georgia)

## What this is

A LangGraph pipeline that helps a Georgian buyer evaluate cars on US salvage auctions
(Copart/IAAI style) and produces a ranked shortlist with real landed costs, fraud flags,
and a recommended max bid. **The system never bids.** The buyer is the only one who bids.

Built as a project for an AI agents course. The architecture is a re-staffing of a claims-
triage system built in class (session 4): intake with a validated form, rule desks, two
agents that negotiate, a human gate, a generator–critic loop, an audit trail.

Tech: Python, LangGraph, LangChain, `anthropic:claude-sonnet-5`, LangSmith tracing.

---

## The core design principle (do not violate this)

**Rules become code. Judgment becomes agents. Agents argue; rules hold the purse.**

Every desk is tagged Rule, Judgment, or Human. Concretely:

- A **Rule** desk is a plain function. No model call. Deterministic, auditable, free.
- A **Judgment** desk calls a model, and its output is always validated/normalized by code
  at the boundary before any rule consumes it.
- **The fork is a rule.** The doorway to judgment must itself be deterministic, so the buyer
  can always answer "why was this car debated?" with a checkable fact.
- Money limits are enforced by rules only. An agent must never be able to talk a car past
  a ceiling.

Two shapes recur and are worth preserving by name:
- **"Judgment estimates; Rule computes and enforces"** (repair estimator → full check)
- **"Rule gates; Judgment decides"** (alert gate <48h → alert judge)

Ordering principle: **cheap and deadly first, expensive and thoughtful last.** A flooded car
must die at the front door having cost nothing. Only survivors reach model calls.

Kill tiers: **the further a car travels before dying, the more explanation its death owes
the buyer.** `kill_tier: "silent"` for obvious garbage (failed hard filters, over budget on
landed cost alone). `kill_tier: "explain"` for cars that died late — those get a one-line
why-not in the weekly report. This comes directly from the stakeholder: "if your system
quietly throws away my dream car, how would I ever know?"

Safe defaults point at caution, not permissiveness: absent airbag info → assume deployed;
absent run-and-drive → assume it doesn't. A wrongly-killed car costs a why-not line; a
wrongly-passed one costs real money.

---

## The buyer (stakeholder) and her requirements

"Tako" — a buyer, not a dealer. Three months deep into auction sites, tired, tight budget,
high standards. Her requirements table (this is the spec; every row is implemented):

| # | Requirement | Tag |
|---|---|---|
| R1 | Read her brief into a structured, validated form | Judgment reads; Rule validates |
| R2 | Kill dealbreakers: type, year, make, title, transmission, airbags, runs-and-drives | Rule — silent kill |
| R3 | Estimate repair as a RANGE; compute landed cost; enforce ceiling and 85%-of-market | Judgment estimates; Rule computes & enforces |
| R4 | Route: clean cars ranked by rule score; borderline cars argued in/out by two agents | Rule routes; two agents negotiate |
| R5 | Mid-week alert if an exceptional car ends soon | Rule gates (<48h); Judgment decides |
| R6 | Detect fraud flags: repeat VIN, suspiciously cheap vs auction baseline | Rule detects; Judgment interprets in the negotiation |
| R7 | Weekly report: costs, flags, max bid, why-nots for near misses | Judgment compiles; rule-like critic gates |
| R8 | Only she ever bids | Human |

Key numbers from the discovery interview:
- Budget **$14,000**, applied to **landed cost only** (`repairs_in_budget: False`) — she may
  fix the car herself or through family, so we don't presume her repair costs. Repairs are
  shown as information.
- "Rational bid" formula: **landed + shop-rate repairs ≤ 85% of the myAuto price** for the
  same car cleared and running. The whole point is saving at least 15%.
- Fraud, in data: same VIN re-listed within **180 days**, or bid below **50%** of the typical
  auction hammer price for that model.
- Shortlist of **5–7**, weekly, with mid-week alerts only for exceptional cars ending
  within **48h**.
- Hedged limits ("ideally under 60,000 km") are **soft** — they rank a car lower, never kill it.

---

## Current state — what is built and working

```
data.py        LISTINGS (5 mock cars), AUCTION_HISTORY, MARKET_PRICES,
               AUCTION_BASELINES, REPAIR_REFERENCE, RATES, BUYER_PROFILE
repo.py        THE ONLY FILE THAT KNOWS WHERE DATA LIVES.
               accessors + live rs.ge customs API + live NBG FX API
filters.py     hard_filters()          — Rule, silent kill
costs.py       landed_cost(), early_budget_check()  — Rule
flags.py       fraud_flags()           — Rule, detects only, never kills
estimator.py   estimate_repairs()      — Judgment, returns low/likely/high + line items
check.py       full_check(), dispatch() — Rule computes, Rule routes (the fork)
intake.py      intake_brief(), intake_listing() — Judgment + normalization
test_pipeline.py  runs all 5 cars through everything, prints each car's fate
```

### Live external APIs (both working, both cached, both with fallbacks)

**rs.ge customs calculator** — unauthenticated, verified against their own UI:
```
POST https://www.rs.ge/RsGe.Module/CarClearance/Calculate
params: Celi=<car year>, Zravismoculoba=<engine litres>, hybridCar, elektroCar,
        sWheel, SportCar, ClassicCar  (all lowercase "true"/"false")
returns: {"Sabgad": "<customs duty GEL>", "Aqcizi": "<excise GEL>", "sum": "<total GEL>"}
```
Verified: 2022 / 2.4L → excise 3600, duty 144, sum 3744; site shows 4224 total, i.e.
`sum + 480 GEL` fixed documentation. **VAT (18%) is NOT included** — we add it ourselves on
base = car value + freight + excise + duty. Responses are cached to `customs_cache.json`.

**NBG FX** — `GET https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/calculator/`
with `codeFrom=USD&codeTo=GEL&quantity=1`. Cached per process, falls back to
`RATES["gel_per_usd"]`.

Both are wrapped in `repo.py` so a future FastAPI + Postgres backend is a one-file swap.
**Keep all data access behind repo.py accessors. Never import `data.py` directly from a desk.**

### Current behaviour of the 5 test cars

- **Tucson** — dies at filters (flood title), silent
- **RAV4** — dies at filters (airbags deployed, doesn't run), silent
- **Kona** — passes, trips both fraud flags (repeat VIN + 45% of baseline) → NEGOTIATION
- **Sportage** — passes everything, borderline-ish on the savings rule → ranked list
- **HR-V** — clean sail-through → ranked list

---

## What is NOT built yet (in priority order)

### 1. The negotiation (Phase 4b) — the last hard piece, ~2–3h
Two agents with opposing jobs, a shared transcript, strict turn-taking, and a rule that
extracts the verdict. Follow the session-4 advocate/adjuster pattern:

- **DEFENDER** — argues the car in: cites budget headroom, savings vs market, evidence.
  Concedes real problems honestly; doesn't defend obvious fraud.
- **CRITIC** — argues it out: fraud flags, hidden-risk from the estimate, repair spread,
  what the market may know that the listing doesn't say.
- They see the same case brief before every turn (listing, landed cost breakdown, flags,
  repair range + line items + hidden_risk, market comparison).
- 2–3 sentences per turn. The transcript IS their shared memory — agents have no telepathy.
- **Fence: max 3 critic rounds**, then the car routes to the buyer undecided rather than
  looping forever.
- Exit signals: defender starts a line with `ACCEPT` (concedes the car is out), critic starts
  with `VERDICT: IN` / `VERDICT: OUT`.
- The verdict is extracted **by regex, in a rule** — never by asking a model what happened.
- The full transcript rides with the car into the report. That is the audit trail.
- **The max bid is set by rules, not by the agents.** Agents decide in/out; the number comes
  from the savings formula (max bid = whatever keeps landed + likely repairs ≤ 85% of market).

### 2. Ranking + shortlist (~1h)
Rule-scored on her stated preference order: damage severity > owners > mileage, plus
`soft_limits.max_mileage_km` (over the limit ranks lower, never kills) and `nice_to_have`
(hybrid, not white). Top 5–7. Negotiation survivors join the list with their transcript
attached.

### 3. Report drafter + critic (~2h)
- **Drafter (Judgment)**: for each shortlisted car — full cost breakdown (bid, auction fee,
  freight, port, excise, duty, VAT, docs), flags and how the negotiation interpreted them,
  recommended max bid, repair range with line items. Plus a why-not line for every
  `kill_tier: "explain"` car.
- **Critic (rule-like Judgment)**: a fixed checklist — every car has a cost breakdown? every
  detected flag appears? every recommendation carries a max bid? every explained kill has a
  why-not? Bounces incomplete reports back to the drafter, max 2 rewrites, then queues for
  the buyer. This is the 12,000-GEL-fine lesson from class: nobody grades their own homework.

### 4. Alert branch (~30m)
Runs over the ranked list — it is a **copy, not a detour**. Every survivor is in the weekly
report regardless. `alert_gate` (Rule): does this auction end within 48h? Then `alert_judge`
(Judgment): is it worth interrupting her week, weighed against her preferences? Declining to
alert never removes a car from the report.

### 5. Wire into LangGraph (~2h)
Every desk is already pure dict-in/dict-out, so each becomes a node with a thin wrapper.
- `ClaimState`-style TypedDict holding: `listing`, `landed`, `flags`, `estimate`, `check`,
  `route`, `transcript`, `rounds`, `verdict`, `max_bid`, `report`, `report_feedback`,
  `report_approved`, `report_rounds`, `audit`.
- `audit` is a list every node appends to — that is R8's trail, free if the state is designed
  right.
- Conditional edges for the fork, the negotiation turn-taking, and the critic bounce.
- **Use `SqliteSaver` as the checkpointer**, not `InMemorySaver` — state should survive
  restarts.
- Render the mermaid graph and compare it against the org chart. That comparison is a design
  review.

### 6. Ugly-path testing (~1.5h)
Flooded car, over-budget-after-repairs, deadlocked negotiation (hits the 3-round fence),
failed extraction, failed repair estimate, incomplete report bouncing twice. Assert on
**decision direction and routing**, not exact dollar amounts — judgment has variance and
pretending otherwise is dishonest testing.

### 7. UI (~4–6h, stretch goal — cut this before cutting anything else)
Streamlit or Gradio: paste a listing → watch desks light up → the negotiation streams turn by
turn → final report card. The negotiation streaming is the demo moment. **Do not start this
until the pipeline and tests pass.** A working pipeline with printed output beats a pretty
shell around a broken graph.

### Optional, cheap, nice-to-have
NHTSA vPIC VIN decode (free, no key, `requests.get`) as a `@tool` cross-checking the listing's
claims against the VIN — listing says 2.4L, VIN says 2.0L → flag. ~20 minutes whenever.

---

## Conventions

- Units in field names: `_usd`, `_km`, `_gel`, `_pct`. Never mix currencies in arithmetic —
  convert at the boundary.
- Every desk returns a dict, never bare values. Rule desks return
  `{"passed": bool, "kill_tier": "silent"|"explain"|None, "reason": str}`.
- Judgment desks return `{"ok": bool, ...payload, "note": str}` and **fail loudly**: a failed
  estimate returns `None`, never `0`, so it can't masquerade as a free repair.
- Model output is parsed with a JSON regex extract, then **types are coerced and values are
  normalized** (canonical body types, titles, make/model casing, trim stripped from model
  names). Rule desks match on exact strings, so intake must speak their language.
- `likely` is computed by rule (midpoint of the range), never asked of the model — an agent
  that names its own headline number names a flattering one.
- Keep desks free of side effects. Dict in, dict out. That's what makes them trivially
  wrappable as LangGraph nodes.

---

## Known limitations (these belong in the final handover, don't hide them)

1. Repair estimates are judgment with real variance — the same damage description can return
   noticeably different ranges run to run. Mitigation: ranges not points; rules consume the
   conservative end.
2. Listings lie, and intake reads language. Mitigation: the extracted form rides on every
   report; `extraction_confidence` is recorded; vPIC cross-check (when added) catches spec
   mismatches.
3. Fraud detection is two rules; real fraud adapts. Mitigation: the flag list is designed to
   grow, and the audit trail is training data for better rules.
4. Listings are snapshot mock data — no scraping (Copart/IAAI prohibit it and sit behind
   anti-bot). Customs and FX are live and official. Production swaps `repo.py` for a real
   backend.
5. Nothing here should touch real money until it has run in shadow mode alongside a real
   search season.

## Non-negotiables

- The system never bids, never auto-purchases, never submits anything. It recommends a max
  bid and stops.
- No scraping of Copart/IAAI.
- No agent may override a rule's ceiling.
- Every kill is either silently justified (obvious garbage) or explained (near miss). No car
  ever vanishes without a reason existing somewhere in the state.