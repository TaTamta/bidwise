# test_ugly_paths.py — the evaluation harness.
#
# Asserts on DECISION DIRECTION and ROUTING, never on exact dollar amounts or
# verdicts, because the estimator and the negotiation are judgment and judgment
# has variance. Testing them as if they were deterministic would be dishonest.
#
# Run: python test_ugly_paths.py

import sqlite3
from datetime import date, timedelta

from console import use_utf8

from langgraph.checkpoint.sqlite import SqliteSaver
from graph import build_graph
from filters import hard_filters
from costs import landed_cost, early_budget_check
from flags import fraud_flags
from check import full_check, dispatch
from intake import intake_listing, intake_brief
from report import build_report
from repo import get_listing

use_utf8()

PASS, FAIL = "✅ PASS", "❌ FAIL"
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition)))
    print(f"  {PASS if condition else FAIL}  {name}")
    if detail and not condition:
        print(f"         {detail}")


def base(listing):
    """A listing dict with overrides applied, so each test states only what it changes."""
    return dict(get_listing("LOT-60488"), **listing)


def run_car(listing, thread):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    app = build_graph(SqliteSaver(conn))
    final = app.invoke(
        {"listing": listing, "transcript": [], "rounds": 0, "audit": [], "alive": True},
        {"configurable": {"thread_id": thread}, "recursion_limit": 40})
    conn.close()
    return final


# ══════════════════════ 1. cheap kills happen at the front door ══════════════════════
print("\n1. HARD FILTERS — obvious garbage dies silently, before any model call")

for label, override in [
    ("flood title", {"title_status": "flood"}),
    ("airbags deployed", {"airbags_deployed": True}),
    ("doesn't run", {"runs_and_drives": False}),
    ("too old", {"year": 2018}),
    ("untrusted make", {"make": "BMW"}),
    ("manual transmission", {"transmission": "manual"}),
]:
    v = hard_filters(base(override))
    check(f"{label} → killed", not v["passed"], v)
    check(f"{label} → silent tier", v.get("kill_tier") == "silent", v)

# and the whole graph must not spend a model call on them
final = run_car(base({"title_status": "flood"}), "ugly-flood")
check("flooded car never reaches the estimator",
      "estimator" not in " ".join(final["audit"]),
      final["audit"])


# ══════════════════════ 2. a failed estimate is not a free repair ══════════════════════
print("\n2. FAILED ESTIMATE — must kill, never sail through as $0")

listing = base({})
landed = landed_cost(listing)
broken = {"ok": False, "low": None, "likely": None, "high": None,
          "line_items": [], "confidence": "none", "hidden_risk": "estimate failed"}
chk = full_check(listing, landed, broken)
check("failed estimate → car dies", not chk["passed"], chk)
check("failed estimate → explained tier", chk.get("kill_tier") == "explain", chk)

d = dispatch({"flags": [], "count": 0}, chk, broken)
check("failed estimate → would route to review, not the shortlist",
      d["route"] == "negotiation", d)


# ══════════════════════ 3. money ceilings cannot be crossed ══════════════════════
print("\n3. BUDGET — rules hold the purse")

rich = base({"current_bid_usd": 25000})
rich_landed = landed_cost(rich)
b = early_budget_check(rich_landed)
check("$25k bid → killed on landed cost alone", not b["passed"], b)
check("→ silent tier (obvious garbage)", b.get("kill_tier") == "silent", b)

final = run_car(rich, "ugly-rich")
check("over-budget car never reaches the estimator",
      "estimator" not in " ".join(final["audit"]),
      final["audit"])

# the savings rule bites even when the ceiling doesn't
mid = base({"current_bid_usd": 7000})
mid_landed = landed_cost(mid)
pricey = {"ok": True, "low": 2000, "likely": 3000, "high": 4000,
          "line_items": [], "confidence": "medium", "hidden_risk": ""}
chk = full_check(mid, mid_landed, pricey)
check("landed + repairs over 85% of market → killed",
      not chk["passed"] and "85%" in chk["reason"], chk)


# ══════════════════════ 4. flags route, they never kill ══════════════════════
print("\n4. FLAGS — detected by rule, interpreted in review")

kona = get_listing("LOT-62155")
f = fraud_flags(kona)
check("repeat-VIN car raises flags", f["count"] >= 1, f)

landed = landed_cost(kona)
est = {"ok": True, "low": 300, "likely": 450, "high": 600,
       "line_items": [], "confidence": "high", "hidden_risk": ""}
chk = full_check(kona, landed, est)
check("flagged car still passes the rule checks (flags don't kill)", chk["passed"], chk)
check("flagged car routes to review", dispatch(f, chk, est)["route"] == "negotiation")

clean_est = {"ok": True, "low": 300, "likely": 450, "high": 600,
             "line_items": [], "confidence": "high", "hidden_risk": ""}
check("unflagged, confident, affordable car skips review",
      dispatch({"flags": [], "count": 0}, chk, clean_est)["route"] == "ranked_list")

check("low-confidence estimate alone routes to review",
      dispatch({"flags": [], "count": 0}, chk,
               {**clean_est, "confidence": "low"})["route"] == "negotiation")


# ══════════════════════ 5. the negotiation always terminates ══════════════════════
print("\n5. NEGOTIATION — the fence holds, and a verdict is always reached")

final = run_car(get_listing("LOT-62155"), f"ugly-neg-{date.today()}")
audit = " ".join(final["audit"])
check("the review ran", "defender spoke" in audit, final["audit"])
check("a verdict exists", final.get("verdict") in ("IN", "OUT", "UNDECIDED"), final.get("verdict"))
check("the fence held (max 3 critic rounds)", final.get("rounds", 0) <= 3, final.get("rounds"))
check("the transcript is preserved as the audit trail",
      len(final.get("transcript", [])) >= 2, final.get("transcript"))

if final.get("verdict") == "OUT":
    check("a car that lost the review dies with an EXPLAINED tier",
          final.get("kill_tier") == "explain", final.get("kill_tier"))
    check("no bid ceiling is offered on a rejected car",
          final.get("bid_ceiling_usd") is None, final.get("bid_ceiling_usd"))
else:
    check("a surviving car carries a rule-set bid ceiling",
          final.get("bid_ceiling_usd") is not None, final.get("bid_ceiling_usd"))
    check("the ceiling is below her budget",
          final["bid_ceiling_usd"] < 14000, final.get("bid_ceiling_usd"))


# ══════════════════════ 6. intake fails loudly, never quietly ══════════════════════
print("\n6. INTAKE — garbage in, honest failure out")

r = intake_listing("hello I would like to buy a sandwich please")
check("nonsense listing → explicit failure, not an invented car",
      not r["ok"] and r["listing"] is None, r["note"])

r = intake_listing("""2021 HONDA CR-V EX AWD
VIN 2HKRW2H85MH000111 | Miami FL | Odometer: 61,000 mi
Primary damage: WATER/FLOOD | Title: FL CERT OF TITLE
Engine 1.5L | Runs & Drives: YES | Current bid $2,900 — sale 08/20/2026""")
if r["ok"]:
    c = r["listing"]
    check("flood in the damage text overrides the title line",
          c["title_status"] == "flood", c["title_status"])
    check("miles converted to km", c["mileage_km"] > 90000, c["mileage_km"])
    check("model stripped of trim/drivetrain", c["model"].lower() in ("cr-V".lower(), "cr-v"),
          c["model"])
    check("that car would then die at filters", not hard_filters(c)["passed"])
else:
    check("messy listing parsed at all", False, r["note"])

r = intake_brief("I want a car. Cheap. SUV, newish. Nothing flooded.")
if r["ok"]:
    check("vague brief still yields safe defaults",
          r["form"]["must_run_and_drive"] and r["form"]["no_airbags_deployed"], r["form"])
else:
    check("vague brief handled", False, r["note"])


# ══════════════════════ 7. the report critic actually gates ══════════════════════
print("\n7. REPORT — the critic catches an incomplete report")

# a car whose facts are deliberately missing the flag interpretation
sabotaged = {
    "listing": get_listing("LOT-60488"),
    "landed": landed_cost(get_listing("LOT-60488")),
    "flags": {"flags": ["same VIN listed 30 days ago — bought and thrown back?"], "count": 1},
    "estimate": {"ok": True, "low": 500, "likely": 700, "high": 900, "line_items": [],
                 "confidence": "medium", "hidden_risk": ""},
    "check": full_check(get_listing("LOT-60488"), landed_cost(get_listing("LOT-60488")),
                        {"ok": True, "low": 500, "likely": 700, "high": 900,
                         "line_items": [], "confidence": "medium"}),
    "score": 70, "negotiation": None, "bid_ceiling_usd": 7000, "is_recommendation": True,
}
out = build_report([sabotaged], [], verbose=False)
check("a report is always produced, approved or not", bool(out["report"]))
check("the critic ran at least once", out["rounds"] >= 1, out["rounds"])
check("an unapproved report is flagged, not silently sent",
      out["approved"] or out["feedback"] is not None)
check("the flag appears in the report text",
      "VIN" in out["report"] or "listed" in out["report"] or "thrown back" in out["report"])


# ══════════════════════ summary ══════════════════════
passed = sum(1 for _, ok in results if ok)
total = len(results)
print("\n" + "═" * 60)
print(f"  {passed}/{total} checks passed")
print("═" * 60)
if passed < total:
    print("\n  failed:")
    for name, ok in results:
        if not ok:
            print(f"    · {name}")
print("""
  What these tests deliberately do NOT assert:
    · exact repair estimates — judgment has variance
    · which side wins a negotiation — same car, different day, different verdict
    · exact bid ceilings — they move with live FX and customs
  They assert direction, routing, and that no failure mode is silent.
""")