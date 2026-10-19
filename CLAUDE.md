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
| R6 | Detect fraud flags: repeat VIN, suspiciously cheap vs auction baseline, listing vs VIN mismatch | Rule detects; Judgment interprets in the negotiation |
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

## Current state — the full pipeline is built

Everything in the requirements table is implemented, wired into LangGraph, tested and
demoed. README.md is the public write-up; keep it and this file in sync.

```
data.py           mock data: 6 LISTINGS, AUCTION_HISTORY, MARKET_PRICES,
                  AUCTION_BASELINES, REPAIR_REFERENCE, RATES, BUYER_PROFILE
repo.py           THE ONLY FILE THAT KNOWS WHERE DATA LIVES.
                  accessors + live rs.ge customs + live NBG FX + NHTSA vPIC VIN decode,
                  all cached, all with fallbacks
intake.py         intake_brief(), intake_listing()   — Judgment + normalization
filters.py        hard_filters()                     — Rule, silent kill
costs.py          landed_cost(), early_budget_check() — Rule
flags.py          fraud_flags()                      — Rule, detects only, never kills
                  (repeat VIN, too cheap vs baseline, listing vs VIN mismatch)
estimator.py      estimate_repairs()                 — Judgment, low/high + line items
check.py          full_check(), dispatch()           — Rule computes, Rule routes (the fork)
negotiation.py    negotiate(), bid_ceiling()         — two agents, regex verdict, MAX_ROUNDS = 3
tools.py          tools the negotiators may call mid-turn (vin_record, past_auctions,
                  tbilisi_price, auction_norm, repair_price)
ranking.py        score_car(), build_shortlist()     — Rule, her preference order
report.py         drafter ⇄ compliance critic, MAX_REWRITES = 2
state.py          CarState — the case file; `audit` is the trail every node appends to
graph.py          LangGraph StateGraph; SqliteSaver checkpointer via open_graph()
run.py            run_search(): every listing → graph → shortlist → report → alerts
                  (alert_gate is the Rule, alert_judge the Judgment)
ui.py             Streamlit front end, streams the graph node by node
console.py        use_utf8() — keeps box-drawing/emoji output from crashing Windows consoles
test_ugly_paths.py  evaluation harness — asserts direction and routing, never exact amounts
```

### Graph shape

```
START → filters → landed → flags → estimate → check → route_note
          │         │                          │          │
          └─ END    └─ END                     └─ END     ├─ clean ──────────→ rank → END
          (each rule desk can end the run)                └─ borderline → defender ⇄ critic
                                                                       → settle → rank | END
```

`after_defender`: `ACCEPT` → settle. `after_critic`: `VERDICT: IN|OUT` or rounds ≥ 3 → settle.

### Live external APIs (all cached, all with fallbacks)

**rs.ge customs calculator** — unauthenticated, verified against their own UI:
```
POST https://www.rs.ge/RsGe.Module/CarClearance/Calculate
params: Celi=<car year>, Zravismoculoba=<engine litres>, hybridCar, elektroCar,
        sWheel, SportCar, ClassicCar  (all lowercase "true"/"false")
returns: {"Sabgad": "<customs duty GEL>", "Aqcizi": "<excise GEL>", "sum": "<total GEL>"}
```
Verified: 2022 / 2.4L → excise 3600, duty 144, sum 3744; site shows 4224 total, i.e.
`sum + 480 GEL` fixed documentation. **VAT (18%) is NOT included** — we add it ourselves on
base = car value + freight + excise + duty. Cached to `customs_cache.json`.

**NBG FX** — `GET https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/calculator/`
with `codeFrom=USD&codeTo=GEL&quantity=1`. Cached per process, falls back to
`RATES["gel_per_usd"]`.

**NHTSA vPIC** — `DecodeVinValues/{vin}`, free, no key. Cached to `vin_cache.json`. An
unreachable decoder or unrecognised VIN returns `{}` and must never count as a mismatch.

`bidwise.sqlite` and both cache files are created at runtime and gitignored — never commit
them.

**Keep all data access behind repo.py accessors. Never import `data.py` directly from a desk.**
A future FastAPI + Postgres backend is a one-file swap.

### The 6 test listings

| Lot | Car | Designed to exercise |
|---|---|---|
| LOT-61077 | 2022 Hyundai Tucson | flood title → silent kill at filters |
| LOT-59930 | 2021 Toyota RAV4 | airbags deployed, doesn't run → silent kill at filters |
| LOT-62155 | 2022 Hyundai Kona | both fraud flags (repeat VIN + too cheap) → negotiation |
| LOT-58412 | 2022 Kia Sportage | low-confidence estimate on a rear hit → borderline |
| LOT-60488 | 2023 Honda HR-V | clean sail-through → ranked list |
| LOT-63220 | 2022 Toyota Corolla Cross | one soft flag, trivial damage, big margin — the defender's best case |

The VINs are invented, so the vPIC cross-check no-ops on them by design. Verdicts on the
negotiated cars vary run to run. That is expected; don't "fix" it.

### Commands

```bash
pip install -r requirements.txt     # pinned; built and tested on Python 3.14
streamlit run ui.py                  # the demo
python run.py                        # the weekly search in the terminal
python test_ugly_paths.py            # the evaluation harness
```

---

## Next ideas (not built — from the README's limitations)

1. **Act on an incomplete brief.** `intake_brief` already marks a brief incomplete and lists
   what to ask; `run.py` should stop and ask her before searching on guessed constraints.
2. **Shadow mode.** Run alongside a real search season and score recommendations against
   what actually happened, before anything touches real money.
3. **Real data backend.** Swap `repo.py` for FastAPI + Postgres. Still no scraping of
   Copart/IAAI.
4. **Grow the fraud rules** using the audit trail as training data.

Any new desk must follow the Rule / Judgment / Human tagging and the conventions below.

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
   report; `extraction_confidence` is recorded; the vPIC cross-check catches year, make and
   engine mismatches (not damage, mileage or title history).
3. Fraud detection is three rules; real fraud adapts. Mitigation: the flag list is designed to
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