# run.py — the whole company, one command.
# Runs every listing through the graph, collects the survivors and the
# explained deaths, then builds the weekly report and the alert list.

import sqlite3
from datetime import datetime, date

from console import use_utf8

from repo import get_listings, buyer_profile
from graph import build_graph
from ranking import build_shortlist
from report import build_report
from langgraph.checkpoint.sqlite import SqliteSaver


def run_search(verbose=True, db_path="bidwise.sqlite"):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    app = build_graph(SqliteSaver(conn))

    survivors, explained_deaths, silent_deaths = [], [], []

    for listing in get_listings():
        config = {"configurable": {"thread_id": f"{listing['lot_id']}-{date.today()}"},
                  "recursion_limit": 40}
        if verbose:
            print(f"▸ {listing['lot_id']} {listing['year']} {listing['make']} {listing['model']}")

        final = app.invoke(
            {"listing": listing, "transcript": [], "rounds": 0, "audit": [], "alive": True},
            config)

        if final.get("alive"):
            car = {
                "listing": final["listing"], "landed": final["landed"],
                "flags": final["flags"], "estimate": final["estimate"],
                "check": final["check"], "route_reason": final.get("route_reason", ""),
                "score": final.get("score"), "score_parts": final.get("score_parts", {}),
                "audit": final.get("audit", []),
                "bid_ceiling_usd": final.get("bid_ceiling_usd"),
                "is_recommendation": final.get("is_recommendation", False),
                "negotiation": None,
            }
            if final.get("verdict"):
                car["negotiation"] = {
                    "verdict": final["verdict"], "ended_by": final.get("ended_by"),
                    "rounds": final.get("rounds", 0),
                    "transcript": final.get("transcript", []),
                    "bid_ceiling_usd": final.get("bid_ceiling_usd"),
                    "is_recommendation": final.get("is_recommendation", False),
                }
            survivors.append(car)
            if verbose:
                print(f"   ✅ survived — score {final.get('score')}")
        else:
            row = (final["listing"], final.get("kill_reason", "unknown"))
            if final.get("kill_tier") == "explain":
                explained_deaths.append(row)
            else:
                silent_deaths.append(row)
            if verbose:
                print(f"   ☠️  [{final.get('kill_tier')}] {final.get('kill_reason', '')[:90]}")

    conn.close()

    ranked = build_shortlist(survivors)
    alerts = find_alerts(ranked["shortlist"])

    return {"shortlist": ranked["shortlist"], "ranked_out": ranked["ranked_out"],
            "explained_deaths": explained_deaths, "silent_deaths": silent_deaths,
            "alerts": alerts}


# ─────────────────────────── the alert branch ───────────────────────────
# A COPY, not a detour: every survivor is in the weekly report regardless.
# The alert only asks whether she should hear about a car sooner.

def alert_gate(car, now=None):
    """RULE: does this auction end inside her alert window?"""
    now = now or datetime.now()
    p = buyer_profile()
    try:
        ends = datetime.fromisoformat(car["listing"]["auction_end_date"])
    except Exception:
        return {"in_window": False, "hours_left": None}
    hours = (ends - now).total_seconds() / 3600
    return {"in_window": 0 < hours <= p["alert_window_hours"], "hours_left": round(hours, 1)}


def alert_judge(car, hours_left):
    """JUDGMENT: is this worth interrupting her week? Rule gates; judgment decides."""
    from langchain.chat_models import init_chat_model
    model = init_chat_model("anthropic:claude-sonnet-5")
    p = buyer_profile()
    l, chk = car["listing"], car["check"]

    answer = model.invoke(
        "You decide whether to interrupt a busy buyer's week with a mid-week alert about a car "
        "whose auction is ending soon. She gets a full report every weekend anyway, so a "
        "mediocre alert costs her trust. Only wake her for something she would be sorry to miss.\n\n"
        f"CAR: {l['year']} {l['make']} {l['model']}, {l.get('mileage_km', 0):,} km, "
        f"{l['damage_description']}\n"
        f"ALL-IN: ${chk['likely_total_usd']:,.0f} vs an ${chk['savings_cap_usd']:,.0f} cap\n"
        f"SCORE: {car.get('score')} / 100\n"
        f"HER SOFT PREFERENCES: {', '.join(p.get('nice_to_have', [])) or 'none'}\n"
        f"AUCTION ENDS IN: {hours_left} hours\n\n"
        "Reply ALERT or WAIT on the first line, then one sentence of reasoning."
    ).text

    first = next((ln for ln in answer.splitlines() if ln.strip()), "")
    return {"alert": first.strip().lstrip("*#>-• ").upper().startswith("ALERT"),
            "why": answer}


def find_alerts(shortlist):
    """Only survivors can be urgent — you never hurry her toward a car the
    system itself killed."""
    out = []
    for car in shortlist:
        gate = alert_gate(car)
        if not gate["in_window"]:
            continue
        verdict = alert_judge(car, gate["hours_left"])
        if verdict["alert"]:
            out.append({"car": car, "hours_left": gate["hours_left"], "why": verdict["why"]})
    return out


# ─────────────────────────── entry point ───────────────────────────

if __name__ == "__main__":
    use_utf8()

    print("═" * 66)
    print("BidWise — weekly search")
    print("═" * 66)

    result = run_search()

    print("\n" + "═" * 66)
    print(f"📄 REPORT — {len(result['shortlist'])} shortlisted, "
          f"{len(result['explained_deaths'])} explained death(s), "
          f"{len(result['silent_deaths'])} killed silently")
    print("═" * 66 + "\n")

    out = build_report(result["shortlist"], result["explained_deaths"])

    print("\n" + "─" * 66)
    if not out["approved"]:
        print("⚠️  COMPLIANCE NEVER CLEARED THIS REPORT — it goes to her flagged\n")
    print(out["report"])

    if result["alerts"]:
        print("\n" + "═" * 66)
        print(f"⏰ MID-WEEK ALERTS ({len(result['alerts'])})")
        print("═" * 66)
        for a in result["alerts"]:
            l = a["car"]["listing"]
            print(f"\n  {l['year']} {l['make']} {l['model']} — ends in {a['hours_left']}h")
            print(f"  {a['why']}")
    else:
        print("\n(no mid-week alerts — nothing ends within the window, "
              "or nothing was worth interrupting her for)")

    print("\n" + "─" * 66)
    print("She decides. The system never bids.")