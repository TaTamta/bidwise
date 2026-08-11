# ui.py — Streamlit front end. Streams the graph node by node so the desks
# light up in order and the negotiation appears turn by turn.
#
# Run: streamlit run ui.py

import sqlite3
from datetime import date

import streamlit as st
from langgraph.checkpoint.sqlite import SqliteSaver

from repo import get_listings, buyer_profile
from graph import build_graph
from ranking import build_shortlist
from report import build_report
from run import alert_gate, alert_judge

st.set_page_config(page_title="BidWise", page_icon="🚗", layout="wide")

# ─────────────────────────── styling ───────────────────────────
st.markdown("""
<style>
  .desk {padding:.45rem .8rem;border-radius:6px;margin:.2rem 0;font-size:.9rem;
         border-left:3px solid #d9d9d6;background:#fafaf9}
  .desk-rule {border-left-color:#2E3238}
  .desk-agent {border-left-color:#D99A2B;background:#fdf8f0}
  .desk-kill {border-left-color:#B84A3A;background:#fdf3f1}
  .turn {padding:.7rem .9rem;border-radius:8px;margin:.35rem 0;font-size:.92rem}
  .turn-def {background:#fdf8f0;border-left:3px solid #D99A2B}
  .turn-crit {background:#f6f6f5;border-left:3px solid #6C7078}
  .verdict {font-weight:700;letter-spacing:.03em}
</style>
""", unsafe_allow_html=True)

st.title("🚗 BidWise")
st.caption("Salvage-auction cars, evaluated. Rules hold the purse; agents argue. "
           "**The system never bids.**")

# ─────────────────────────── sidebar ───────────────────────────
p = buyer_profile()
with st.sidebar:
    st.subheader("Her requirements")
    st.write(f"**Budget** ${p['max_total_usd']:,} — landed cost"
             f"{' (repairs included)' if p['repairs_in_budget'] else ', repairs are her own'}")
    st.write(f"**Year** {p['min_year']}+  ·  **Body** {', '.join(p['body_types'])}")
    st.write(f"**Makes** {', '.join(p['trusted_makes'])}")
    st.write(f"**Transmission** {p['transmission']}")
    st.write(f"**Savings target** {p['target_savings_pct']:.0%} under Tbilisi market")
    st.divider()
    st.caption("Soft (ranks lower, never kills)")
    st.write(f"mileage ≤ {p['soft_limits']['max_mileage_km']:,} km  ·  "
             f"{', '.join(p['nice_to_have'])}")
    st.divider()
    st.caption("Live data: rs.ge customs · NBG rate · NHTSA vPIC")

listings = get_listings()
st.write(f"**{len(listings)} listings** in this week's batch.")
go = st.button("▶ Run the search", type="primary", use_container_width=True)

# ─────────────────────────── the run ───────────────────────────

NODE_LABEL = {
    "filters": ("🚫 hard filters", "rule"),
    "landed": ("🧮 landed cost", "rule"),
    "flags": ("🕵️ fraud desk", "rule"),
    "estimate": ("🔧 repair estimator", "agent"),
    "check": ("⚖️ full check", "rule"),
    "route_note": ("🚦 the fork", "rule"),
    "defender": ("🛡 defender", "agent"),
    "critic": ("⚔ critic", "agent"),
    "settle": ("📌 settle", "rule"),
    "rank": ("📋 ranked", "rule"),
}


def desk_line(text, kind="rule"):
    return f'<div class="desk desk-{kind}">{text}</div>'


if go:
    conn = sqlite3.connect("bidwise.sqlite", check_same_thread=False)
    app = build_graph(SqliteSaver(conn))

    survivors, explained, silent = [], [], []

    for listing in listings:
        title = f"{listing['year']} {listing['make']} {listing['model']} · {listing['lot_id']}"
        with st.expander(title, expanded=True):
            col_desks, col_debate = st.columns([1, 1.4])
            desks_box = col_desks.container()
            debate_box = col_debate.container()
            debate_started = False

            state = {"listing": listing, "transcript": [], "rounds": 0,
                     "audit": [], "alive": True}
            config = {"configurable": {"thread_id": f"{listing['lot_id']}-{date.today()}"},
                      "recursion_limit": 40}

            final = None
            seen_turns = 0
            for chunk in app.stream(state, config, stream_mode="values"):
                final = chunk
                audit = chunk.get("audit", [])
                if audit:
                    last = audit[-1]
                    kind = "kill" if "KILL" in last else \
                        ("agent" if any(k in last for k in ("estimator", "defender", "critic")) else "rule")
                    desks_box.markdown(desk_line(last, kind), unsafe_allow_html=True)

                # stream negotiation turns as they appear
                turns = chunk.get("transcript", [])
                if turns and not debate_started:
                    debate_box.markdown("**🤝 The review**")
                    debate_started = True
                for t in turns[seen_turns:]:
                    who = "def" if t.startswith("DEFENDER") else "crit"
                    icon = "🛡 **Defender**" if who == "def" else "⚔ **Critic**"
                    body = t.split(": ", 1)[1] if ": " in t else t
                    debate_box.markdown(
                        f'<div class="turn turn-{who}">{icon}<br>{body}</div>',
                        unsafe_allow_html=True)
                seen_turns = len(turns)

            # ── outcome ──
            if final.get("verdict"):
                v = final["verdict"]
                colour = {"IN": "🟢", "OUT": "🔴", "UNDECIDED": "🟡"}[v]
                debate_box.markdown(
                    f'<div class="verdict">{colour} VERDICT: {v} '
                    f'<span style="font-weight:400;color:#6C7078">'
                    f'({final.get("ended_by")})</span></div>', unsafe_allow_html=True)

            if final.get("alive"):
                car = {"listing": final["listing"], "landed": final["landed"],
                       "flags": final["flags"], "estimate": final["estimate"],
                       "check": final["check"], "route_reason": final.get("route_reason", ""),
                       "score": final.get("score"), "score_parts": final.get("score_parts", {}),
                       "bid_ceiling_usd": final.get("bid_ceiling_usd"),
                       "is_recommendation": final.get("is_recommendation", False),
                       "negotiation": None}
                if final.get("verdict"):
                    car["negotiation"] = {
                        "verdict": final["verdict"], "ended_by": final.get("ended_by"),
                        "rounds": final.get("rounds", 0),
                        "transcript": final.get("transcript", []),
                        "bid_ceiling_usd": final.get("bid_ceiling_usd"),
                        "is_recommendation": final.get("is_recommendation", False)}
                survivors.append(car)

                c1, c2, c3 = st.columns(3)
                c1.metric("landed", f"${final['landed']['landed_total_usd']:,.0f}")
                c2.metric("score", final.get("score"))
                if final.get("bid_ceiling_usd"):
                    c3.metric("max bid", f"${final['bid_ceiling_usd']:,.0f}")
            else:
                tier = final.get("kill_tier")
                (explained if tier == "explain" else silent).append(
                    (final["listing"], final.get("kill_reason", "")))
                st.error(f"**{tier}** — {final.get('kill_reason', '')[:300]}")

    conn.close()

    # ── shortlist ──
    st.divider()
    ranked = build_shortlist(survivors)
    st.subheader(f"📋 Shortlist — {len(ranked['shortlist'])} car(s)")
    for i, car in enumerate(ranked["shortlist"], 1):
        l = car["listing"]
        bits = [f"**{i}. {l['year']} {l['make']} {l['model']}**",
                f"score {car['score']}",
                f"all-in ${car['check']['likely_total_usd']:,.0f}"]
        if car.get("bid_ceiling_usd"):
            bits.append(f"max bid ${car['bid_ceiling_usd']:,.0f}")
        if car["negotiation"]:
            bits.append("🤝 survived review")
        st.write("  ·  ".join(bits))

    # ── report ──
    st.divider()
    st.subheader("📄 The weekly report")
    with st.status("Drafter ⇄ compliance critic…", expanded=True) as status:
        out = build_report(ranked["shortlist"], explained, verbose=False)
        st.write(f"{out['rounds']} draft(s) — "
                 f"{'approved ✅' if out['approved'] else 'never cleared ⚠️'}")
        status.update(label=f"Report ready ({out['rounds']} draft(s))", state="complete")

    if not out["approved"]:
        st.warning("Compliance never cleared this report — it goes to her flagged.")
        with st.expander("What compliance objected to"):
            st.text(out["feedback"])
    st.markdown(out["report"])

    # ── alerts ──
    st.divider()
    st.subheader("⏰ Mid-week alerts")
    st.caption("A copy, not a detour — every survivor is in the report regardless.")
    found = False
    for car in ranked["shortlist"]:
        gate = alert_gate(car)
        if not gate["in_window"]:
            continue
        verdict = alert_judge(car, gate["hours_left"])
        if verdict["alert"]:
            found = True
            l = car["listing"]
            st.info(f"**{l['year']} {l['make']} {l['model']}** — ends in "
                    f"{gate['hours_left']}h\n\n{verdict['why']}")
    if not found:
        st.write("Nothing ends soon enough, or nothing was worth interrupting her week for.")

    st.divider()
    st.caption("She decides. The system never bids.")