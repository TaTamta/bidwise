# BidWise

An agent system that helps a Georgian buyer evaluate salvage-title cars from US auctions
and decide what to bid.

**The system never bids.** It reads listings, computes real landed costs against live
government data, screens for fraud patterns, argues the borderline cases out loud between
two opposed agents, and hands the buyer a ranked shortlist with a recommended maximum bid.
The finger on the button is always hers.

---

## The problem

Buying a car from a US auction takes a Georgian buyer 2–3 months of searching and 2 months
of shipping — and can still end in a flooded car with unexpected damage. Evaluating a single
listing properly means checking the VIN, screening for fraud patterns, computing customs and
excise, estimating repair costs, and comparing against local market prices. Hours per car,
across hundreds of cars.

The stakeholder, "Tako", put it plainly during discovery:

> "It takes me hours just to fully evaluate one car. It's hard to filter too-good-to-be-true
> cars from actual gems that still sound like fraud, and to figure out what's rational to
> bid. I want a system that does the background work and gives me a ranked shortlist — I'll
> be the decision maker. **I am not letting AI bid for me.**"

That last sentence is a design constraint, not a preference. It also happens to be legally
convenient: auction platforms prohibit automated bidding.

---

## Design principle

**Rules become code. Judgment becomes agents. Agents argue; rules hold the purse.**

Every desk in the pipeline is tagged Rule, Judgment, or Human:

- A **Rule** desk is a plain function. No model call, deterministic, auditable, free.
- A **Judgment** desk calls a model, and its output is validated and normalized by code
  before any rule consumes it.
- **The fork is a rule.** The doorway into judgment is itself deterministic, so the buyer
  can always answer "why was this car debated?" with a checkable fact.
- Money limits are enforced by rules only. No agent can talk a car past a ceiling.

Two shapes recur:

| Shape | Where |
|---|---|
| *Judgment estimates; Rule computes and enforces* | repair estimator → full check |
| *Rule gates; Judgment decides* | alert gate (<48h) → alert judge |

Two ordering principles fall out of it:

**Cheap and deadly first, expensive and thoughtful last.** A flooded car dies at the front
door having cost nothing. Only survivors reach a model call.

**The further a car travels before dying, the more explanation its death owes her.** Obvious
garbage dies silently. A car that survived every filter and lost the review gets a one-line
why-not in the report. From her own words: *"if your system quietly throws away my dream car,
how would I ever know?"*

---

## Architecture

```
listing
   │
   ▼
HARD FILTERS ──────────► ☠ silent kill (year, body, make, title, transmission,
   │                                     airbags, doesn't run)
   ▼
LANDED COST ───────────► ☠ silent kill (already over budget before repairs exist)
   │  bid + auction fee + freight + port + excise + duty + VAT + docs
   ▼
FLAG DESK                 flags never kill — they travel to the fork
   │  repeat VIN within 180 days · bid < 50% of the model's auction baseline ·
   │  listing vs. VIN-decoded year, make and engine size
   ▼
REPAIR ESTIMATE           agent · returns a RANGE, never a point
   │  costed line items grounded in Tbilisi shop prices + a hidden-risk caveat
   ▼
FULL CHECK ────────────► ☠ explained death (gets a why-not line)
   │  budget ceiling on landed cost · 85%-of-market savings rule including repairs
   ▼
THE FORK                  rule · 4 tripwires: fraud flags · budget bust ·
   │                      high-end erases the saving · low-confidence estimate
   ├── clean ──────────────────────────────┐
   └── borderline ─► DEFENDER ⇄ CRITIC     │   max 3 rounds, then she decides
                          │                │
                       SETTLE ─────────────┤   rule reads the verdict from the transcript
                          │                │
                          └─► ☠ OUT        │
                                           ▼
                                     RANKED LIST
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
                 ALERT GATE (<48h?)                    REPORT DRAFTER
                        ▼                                     ⇅
                 ALERT JUDGE                            REPORT CRITIC
                        │                                     │
                        └──────────────► SHE DECIDES ◄────────┘
```

The alert branch is a **copy, not a detour**: every survivor is in the weekly report
regardless. The alert only asks whether she should hear about a car sooner.

---

## Requirements → implementation

Every row came from the brief or the discovery interview. The right column is the single
most important engineering decision per row.

| # | Requirement | Tag | Lives in |
|---|---|---|---|
| R1 | Read her brief and raw listings into structured, validated forms | Judgment reads; Rule validates | `intake.py` |
| R2 | Kill dealbreakers: year, body, make, title, transmission, airbags, runs | Rule — silent kill | `filters.py` |
| R3 | Estimate repairs as a range; compute landed cost; enforce the ceiling and the 85% rule | Judgment estimates; Rule computes & enforces | `estimator.py`, `costs.py`, `check.py` |
| R4 | Route: clean cars ranked; borderline cars argued in/out by two agents | Rule routes; agents negotiate | `check.py`, `negotiation.py` |
| R5 | Mid-week alert if an exceptional car ends soon | Rule gates (<48h); Judgment decides | `run.py` |
| R6 | Detect fraud flags: repeat VIN, suspiciously cheap vs auction baseline, listing that contradicts its VIN | Rule detects; Judgment interprets in the review | `flags.py` |
| R7 | Weekly report: costs, flags, max bid, why-nots | Judgment compiles; rule-like critic gates | `report.py` |
| R8 | Only she ever bids | Human | everywhere, by omission |

Key numbers, all from the interview:

- Budget **$14,000**, applied to **landed cost only** — she may repair the car herself or
  through family, so the system doesn't presume her repair costs. Repairs are shown as
  information, not enforced as a limit.
- "Rational bid" formula: **landed + shop-rate repairs ≤ 85% of the myAuto price** for the
  same car cleared and running. The point of five months of effort is saving at least 15%.
- Fraud, in data: same VIN re-listed within **180 days**, or a bid under **50%** of the
  typical auction hammer price for that model.
- Shortlist of **5–7**, weekly, with mid-week alerts only for cars ending within **48h**.
- Hedged limits ("ideally under 60,000 km") are **soft** — they rank a car lower, never kill it.

---

## Live data

Three free official APIs, all cached, with fallbacks so a demo survives a dead connection.

**rs.ge customs calculator** — official excise and customs duty, verified against the
site's own UI (2022 / 2.4L → excise 3,600 GEL, duty 144 GEL; the site's 4,224 GEL total is
`sum + 480` fixed documentation). Note that VAT is **not** included in their figure; the
system adds 18% on a base of car value + freight + excise + duty.

**National Bank of Georgia** — live USD/GEL rate.

**NHTSA vPIC** — decodes the manufacturer's own year, make and engine size from the VIN.
A listing that contradicts its VIN gets a flag; since customs is calculated on engine size,
a wrong engine means a wrong landed cost. An unreachable decoder never counts as a mismatch.

So the landed cost isn't a guess. It's the tax authority's own number and the central bank's
own rate.

Listings, Tbilisi market prices, auction baselines and repair reference prices are hand-copied
snapshots (see limitations).

---

## Running it

Requires Python 3.11+ and an Anthropic API key. LangSmith tracing is optional.

```bash
git clone https://github.com/TaTamta/bidwise.git
cd bidwise
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set ANTHROPIC_API_KEY (and LangSmith, if you use it)
```

```bash
streamlit run ui.py         # the interface — desks light up in order, the review
                            # streams turn by turn, then the report and alerts
python run.py               # the same weekly search, in the terminal
python test_ugly_paths.py   # the evaluation harness (41 checks)
```

State is checkpointed to `bidwise.sqlite`, so runs survive restarts. The database and the
API caches (`customs_cache.json`, `vin_cache.json`) are created at runtime and not committed. Every model call is
traced in LangSmith.

The UI streams the graph node by node (`app.stream(..., stream_mode="values")`) rather than
waiting for a final result — which is why you can watch the defender and the critic argue in
real time instead of seeing a finished transcript appear at once.

---

## Files

```
data.py         listings, auction history, market prices, auction baselines,
                repair reference, rates, buyer profile
repo.py         THE ONLY FILE THAT KNOWS WHERE DATA COMES FROM
                accessors + live rs.ge customs + live NBG FX + NHTSA VIN decode,
                cached with fallbacks
intake.py       agent · brief → requirements form, raw listing → listing dict
filters.py      rule · hard dealbreakers, silent kills
costs.py        rule · full landed cost breakdown + early budget kill
flags.py        rule · fraud detection (detects only, never kills)
estimator.py    agent · repair ranges with costed line items
check.py        rule · the full check and the fork
negotiation.py  agents · defender ⇄ critic, verdict extracted by regex
tools.py        tools the defender and critic can call (VIN record, past auctions, ...)
ranking.py      rule · weighted score on her stated preference order
report.py       agents · drafter ⇄ compliance critic, max 2 rewrites
state.py        the case file every desk reads and writes
graph.py        the org chart, wired as a LangGraph StateGraph
run.py          entry point: search → rank → report → alerts
ui.py           Streamlit front end, streaming the graph node by node
test_ugly_paths.py   the evaluation harness — 41 checks on the ugly paths
```

`repo.py` is the seam. Swapping the mock data for a real backend (scraper + database +
FastAPI) means rewriting one file; nothing else changes.

---

## Design decisions worth defending

**Why two agents instead of one "evaluate this car" agent?** A single agent asked to be both
hopeful and suspicious just picks a mood and hides the tradeoff. Two agents with opposing
jobs make the disagreement *visible*, and the full transcript rides with the car into the
report. In one run the critic beat the defender's proposed mitigation with domain knowledge
neither prompt contained: *"there is no pre-purchase inspection available before bidding on a
US salvage lot — by the time inspection is possible in Tbilisi, she's already spent the
$5,602 in fees, freight and customs."*

**Why is `likely` computed rather than asked?** The estimator returns low and high; a rule
takes the midpoint. An agent that names its own headline number names a flattering one.

**Why does a rule read the verdict?** The negotiation's outcome is extracted from the
transcript with a regex, not by asking a third model what happened. `re.search` cannot be
persuaded.

**Why a compliance critic?** Because the drafter, left alone, will paper over gaps. In
testing it repeatedly tried to relabel the 85% savings *cap* as a recommended bid, and once
invented reviewer conclusions that the transcript didn't contain. The critic rejected three
consecutive drafts before one passed. Nobody grades their own homework.

**Why do safe defaults point at caution?** Absent airbag information → assume deployed.
Absent run-and-drive → assume it doesn't. A wrongly-killed car costs her a why-not line;
a wrongly-passed one costs money.

---

## What this system should not yet be trusted with

1. **Repair estimates are judgment with real variance.** The same damage description has
   produced noticeably different ranges across runs. Mitigation: ranges not points, and the
   rules consume them conservatively. The number is shown to her, never enforced as a limit.
2. **Listings lie, and intake reads language.** Mitigation: the extracted form rides on
   every report and records an extraction confidence, and the VIN decode cross-checks year,
   make and engine size. It can't see damage, mileage or title history, though.
3. **Fraud detection is three rules; real fraud adapts.** Mitigation: the flag list is built to
   grow, and the audit trail is the training data for better rules.
4. **Listings are snapshot data.** Copart and IAAI prohibit scraping and sit behind anti-bot
   protection. Customs and FX are live and official; everything else is hand-copied.
5. **The negotiation's verdicts vary run to run.** Same car, same code, different outcome
   on different days. This is honest — it's what judgment is — and it's why the transcript
   is part of the record rather than just the verdict.
6. **An incomplete brief is detected but not yet acted on.** If she never states a budget,
   `intake_brief` returns a form marked incomplete with a list of what to ask her — but
   `run.py` doesn't stop and ask. It should, before a search runs on guessed constraints.
7. **Nothing here should touch real money until it has run in shadow mode** alongside a real
   search season, with its recommendations judged against what actually happened.

---

## How you know it works

`python test_ugly_paths.py` runs 41 checks over the paths that actually matter: a flooded
car dying before any model call, a failed estimate refusing to masquerade as a free repair,
a bid that can't cross a ceiling, flags that route without killing, a negotiation that always
terminates inside its fence, intake that fails loudly on nonsense, and a report that is never
silently sent unapproved.

What the harness deliberately does **not** assert:

- exact repair estimates — judgment has variance
- which side wins a negotiation — same car, different day, different verdict
- exact bid ceilings — they move with live FX and customs rates

Testing those as if they were fixed would be testing the model's mood. The suite asserts
**direction, routing, and the absence of silent failure** — properties of the architecture,
which should hold every run.

---

Built for an AI agents course. The architecture is a re-staffing of a claims-triage system
built in class: intake with a validated form, rule desks, two agents that negotiate, a
generator–critic loop, a human gate, and an audit trail.