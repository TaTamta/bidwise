# report.py — the drafter writes, a rule-like critic gates. Nobody grades their
# own homework. This is the 12,000-GEL-fine pattern from class: the critic exists
# because an incomplete or embellished report costs her real money.

from dotenv import load_dotenv
load_dotenv()

from langchain.chat_models import init_chat_model

MODEL = "anthropic:claude-sonnet-5"
model = init_chat_model(MODEL)

MAX_REWRITES = 2


def _car_facts(car):
    """Everything the drafter is allowed to use. If it isn't here, it isn't true."""
    l, landed, est, chk = car["listing"], car["landed"], car["estimate"], car["check"]
    cust = landed["customs"]
    lines = [
        f"### {l['year']} {l['make']} {l['model']} — lot {l['lot_id']}",
        f"score: {car.get('score', 'n/a')}  ·  {l.get('mileage_km', 0):,} km  ·  "
        f"{l['title_status']} title  ·  auction ends {l['auction_end_date']}",
        f"damage: {l['damage_description']}",
        "COST BREAKDOWN (USD):",
        f"  hammer bid            {landed['bid_usd']:>9,.0f}",
        f"  auction fee           {landed['auction_fee_usd']:>9,.0f}",
        f"  freight (US + ocean)  {landed['freight_usd']:>9,.0f}",
        f"  port + broker         {landed['port_usd']:>9,.0f}",
        f"  excise                {cust['excise_usd']:>9,.0f}",
        f"  customs duty          {cust['duty_usd']:>9,.0f}",
        f"  VAT                   {cust['vat_usd']:>9,.0f}",
        f"  documentation         {cust['docs_usd']:>9,.0f}",
        f"  LANDED TOTAL          {landed['landed_total_usd']:>9,.0f}",
        f"repairs at Tbilisi shop rates: ${est['low']:,.0f} low / ${est['likely']:,.0f} likely / "
        f"${est['high']:,.0f} high (confidence: {est['confidence']})",
    ]
    for it in est.get("line_items", []):
        lines.append(f"  · {it['work']}: ${it['low']:,.0f}-${it['high']:,.0f} — {it['note']}")

    # the estimator's caveat is NOT a flag. Different thing, different section.
    if est.get("hidden_risk"):
        lines.append(f"ESTIMATOR'S CAVEAT (not a flag, just what a photo can't show): "
                     f"{est['hidden_risk']}")

    lines.append(f"all-in if she pays shop rates: ${chk['likely_total_usd']:,.0f} likely / "
                 f"${chk['high_total_usd']:,.0f} high")
    lines.append(f"85% savings cap: ${chk['savings_cap_usd']:,.0f}")

    if car["flags"]["flags"]:
        lines.append("FRAUD FLAGS RAISED BY THE RULES:")
        lines += [f"  ⚑ {f}" for f in car["flags"]["flags"]]
    else:
        lines.append("FRAUD FLAGS RAISED BY THE RULES: none — this car passed every "
                     "rule check cleanly and was not sent to review.")

    neg = car.get("negotiation")
    if neg:
        lines.append(f"REVIEW TRANSCRIPT — verdict {neg['verdict']} ({neg['ended_by']}, "
                     f"{neg['rounds']} round(s)). Report only what these turns actually say:")
        for turn in neg["transcript"]:
            lines.append(f"  {turn}")
        if neg.get("bid_ceiling_usd") is not None:
            label = "RECOMMENDED MAX BID" if neg.get("is_recommendation") \
                else "CEILING IF SHE PROCEEDS ANYWAY (not a recommendation)"
            lines.append(f"{label}: ${neg['bid_ceiling_usd']:,.0f}")
    else:
        lines.append("REVIEW: none needed — the car was clean on every tripwire, so it went "
                     "straight to the shortlist. This is good news, not a missing step.")
        if car.get("bid_ceiling_usd") is not None:
            lines.append(f"RECOMMENDED MAX BID: ${car['bid_ceiling_usd']:,.0f} "
                         f"(the rule's ceiling — this car cleared every check, so it IS a "
                         f"recommendation, not a caution)")
    return "\n".join(lines)


DRAFT_PROMPT = """You are writing the weekly car-search report for Tako, a buyer importing a
car from US auctions. She is the decision maker — you never tell her to bid, you give her what
she needs to decide.

Write in plain, warm language. No jargon she wouldn't use herself.

The report MUST contain, for every shortlisted car:
- the full cost breakdown, line by line, exactly as given (do not omit lines, do not re-round)
- the repair estimate as a RANGE, never a single number, with its confidence level
- every fraud flag that was raised, and what the review concluded about it
- either a recommended max bid, or — where the review didn't clear the car — an explicit note
  that the number is a ceiling and NOT a recommendation

Critical distinctions, do not blur them:
- A car with NO fraud flags and NO review passed cleanly on the rules. Say so positively.
  Absence of a review is not a gap or an open question — it means nothing was suspicious.
- The estimator's caveat is NOT a fraud flag. It is the normal limit of estimating from
  photos. Never list caveats under flags.
- Report only what the review transcript actually says. Never soften, embellish, or invent a
  reviewer's conclusion. If the critic voted OUT, say the critic voted OUT.

And a "why not" section: one line for each car that got far enough to deserve an explanation.
Never invent a fact. If something isn't in the material below, it doesn't go in the report.

{feedback}

MATERIAL:

SHORTLISTED CARS
{shortlisted}

CARS THAT DIED LATE (these need a one-line why-not each)
{why_nots}
"""

CRITIC_PROMPT = """You are the compliance checker for an outgoing car-search report. You are
a checklist, not a critic of style. Do not comment on tone, warmth, or wording.

Check ONLY these, against the source material:
1. Does every shortlisted car have its full cost breakdown (bid, auction fee, freight, port,
   excise, duty, VAT, documentation, landed total)?
2. Is every repair estimate presented as a range with its confidence level — never a single number?
3. Does every fraud flag in the source appear in the report?
4. Does every car carry either a recommended max bid or an explicit "this is a ceiling, not a
   recommendation" note?
5. Does every car that died late have a why-not line?
6. Are there any numbers in the report that do not appear in the source material?
7. Does anything appear as a "flag" that is NOT listed under FRAUD FLAGS in the source?
   The estimator's caveat is not a flag. Report this as a failure.
8. Does the report describe a clean car (no flags, no review) as having open questions or a
   missing step? That is a failure — a clean car passed.
9. Does the report's account of any review match the transcript? Any softened, embellished or
   invented reviewer conclusion is a failure.

Reply with APPROVE or REJECT alone on the first line, then one line per failed check.

SOURCE MATERIAL:
{material}

REPORT:
{report}
"""


def draft_report(shortlist, why_nots, feedback=""):
    """Judgment compiles. Everything it is allowed to say is in the material."""
    material_short = "\n\n".join(_car_facts(c) for c in shortlist) or "(no cars made the shortlist)"
    material_why = "\n".join(
        f"- {l['year']} {l['make']} {l['model']}: {reason}"
        for l, reason in why_nots) or "(none)"

    note = f"\nYour previous draft was rejected by compliance:\n{feedback}\nFix every point.\n" \
        if feedback else ""

    text = model.invoke(DRAFT_PROMPT.format(
        feedback=note, shortlisted=material_short, why_nots=material_why)).text
    return text, f"{material_short}\n\nWHY-NOTS\n{material_why}"


def check_report(report_text, material):
    """Rule-like judgment: a fixed checklist, no opinions allowed."""
    answer = model.invoke(CRITIC_PROMPT.format(material=material, report=report_text)).text
    first = next((ln for ln in answer.splitlines() if ln.strip()), "")
    ok = first.strip().lstrip("*#>-• ").upper().startswith("APPROVE")
    return {"approved": ok, "feedback": answer}


def build_report(shortlist, why_nots, verbose=True):
    """Drafter ⇄ critic, max 2 rewrites, then it goes to her marked unchecked."""
    feedback, rounds = "", 0
    text, material = "", ""
    while rounds <= MAX_REWRITES:
        text, material = draft_report(shortlist, why_nots, feedback)
        rounds += 1
        verdict = check_report(text, material)
        if verbose:
            print(f"  📝 draft {rounds}: compliance "
                  f"{'APPROVED ✅' if verdict['approved'] else 'REJECTED ❌'}")
            if not verdict["approved"]:
                print(f"     {verdict['feedback'][:400]}")
        if verdict["approved"]:
            return {"report": text, "approved": True, "rounds": rounds, "feedback": None}
        feedback = verdict["feedback"]

    return {"report": text, "approved": False, "rounds": rounds, "feedback": feedback}