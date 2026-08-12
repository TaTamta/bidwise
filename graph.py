# graph.py — the org chart, wired. Every desk is already dict-in/dict-out,
# so each becomes a node with a thin wrapper.
#
# Rules route; agents speak inside nodes. The fork is a conditional edge —
# the doorway to judgment is itself deterministic.

import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from state import CarState
from filters import hard_filters
from costs import landed_cost, early_budget_check
from flags import fraud_flags
from estimator import estimate_repairs
from check import full_check, dispatch
from ranking import score_car
from negotiation import (case_brief, bid_ceiling, MAX_ROUNDS,
                         defender, critic, _speak, ACCEPT_RE, VERDICT_RE)


def _audit(state, line):
    return state.get("audit", []) + [line]


# ─────────────────────────── rule desks ───────────────────────────

def node_filters(state: CarState):
    v = hard_filters(state["listing"])
    out = {"filters": v, "alive": v["passed"],
           "audit": _audit(state, f"filters: {'pass' if v['passed'] else 'KILL — ' + v['reason']}")}
    if not v["passed"]:
        out.update(kill_tier=v["kill_tier"], kill_reason=v["reason"])
    return out


def node_landed(state: CarState):
    landed = landed_cost(state["listing"])
    b = early_budget_check(landed)
    out = {"landed": landed, "budget": b, "alive": b["passed"],
           "audit": _audit(state, f"landed cost: ${landed['landed_total_usd']:,.0f} — {b['reason']}")}
    if not b["passed"]:
        out.update(kill_tier=b["kill_tier"], kill_reason=b["reason"])
    return out


def node_flags(state: CarState):
    f = fraud_flags(state["listing"])
    return {"flags": f,
            "audit": _audit(state, f"fraud desk: {f['count']} flag(s)"
                                   + (f" — {f['flags']}" if f["flags"] else ""))}


def node_estimate(state: CarState):
    e = estimate_repairs(state["listing"])
    note = (f"repairs ${e['low']:,.0f}/${e['likely']:,.0f}/${e['high']:,.0f} "
            f"({e['confidence']} confidence)") if e["ok"] else e["note"]
    return {"estimate": e, "audit": _audit(state, f"estimator: {note}")}


def node_check(state: CarState):
    chk = full_check(state["listing"], state["landed"], state["estimate"])
    out = {"check": chk, "alive": chk["passed"],
           "audit": _audit(state, f"full check: {'pass' if chk['passed'] else 'KILL'} — {chk['reason']}")}
    if not chk["passed"]:
        out.update(kill_tier=chk["kill_tier"], kill_reason=chk["reason"])
    return out


def node_rank(state: CarState):
    car = _car_from_state(state)
    s = score_car(car)
    out = {"score": s["score"], "score_parts": s["parts"], "alive": True,
           "audit": _audit(state, f"ranked: score {s['score']} {s['parts']}")}
    # A clean car still needs a bid ceiling. The rule computes it either way —
    # cars that skipped the review are the SAFEST ones, so withholding a number
    # from them makes no sense.
    if state.get("bid_ceiling_usd") is None:
        out["bid_ceiling_usd"] = bid_ceiling(car)
        out["is_recommendation"] = True
        out["audit"] = out["audit"] + [f"bid ceiling (rule): ${out['bid_ceiling_usd']:,.0f}"]
    return out


# ─────────────────── the negotiation, as turn-taking nodes ───────────────────

def _car_from_state(state):
    return {"listing": state["listing"], "landed": state["landed"], "flags": state["flags"],
            "estimate": state["estimate"], "check": state["check"],
            "route_reason": state.get("route_reason", "")}


def node_defender(state: CarState):
    car = _car_from_state(state)
    transcript = state.get("transcript", [])
    text = _speak(defender, case_brief(car), transcript,
                  "Make your case for this car, or answer the critic's last point.")
    return {"transcript": transcript + [f"DEFENDER: {text}"],
            "audit": _audit(state, "defender spoke")}


def node_critic(state: CarState):
    car = _car_from_state(state)
    transcript = state.get("transcript", [])
    text = _speak(critic, case_brief(car), transcript,
                  "Answer the defender. Commit to a verdict as soon as you can defend one.")
    rounds = state.get("rounds", 0) + 1
    return {"transcript": transcript + [f"CRITIC: {text}"], "rounds": rounds,
            "audit": _audit(state, f"critic spoke (round {rounds})")}


def node_settle(state: CarState):
    """RULE reads the verdict out of the transcript. It cannot be persuaded."""
    transcript = state.get("transcript", [])
    last = transcript[-1] if transcript else ""
    car = _car_from_state(state)

    if ACCEPT_RE.search(last):
        verdict, ended_by = "OUT", "defender conceded"
    else:
        m = VERDICT_RE.search(last)
        if m:
            verdict, ended_by = m.group(1).upper(), "critic committed"
        else:
            verdict, ended_by = "UNDECIDED", f"no verdict after {MAX_ROUNDS} rounds — she decides"

    out = {"verdict": verdict, "ended_by": ended_by,
           "is_recommendation": verdict == "IN",
           "bid_ceiling_usd": bid_ceiling(car) if verdict in ("IN", "UNDECIDED") else None,
           "alive": verdict != "OUT",
           "audit": _audit(state, f"settle: verdict {verdict} ({ended_by})")}

    if verdict == "OUT":
        raw = last.replace("CRITIC: ", "").strip()
        cut = raw[:400]
        if "." in cut:                      # cut at a sentence end, not mid-word
            cut = cut[:cut.rfind(".") + 1]
        out.update(kill_tier="explain", kill_reason=f"lost the review — {cut}")
    return out


# ─────────────────────────── forks (all rules) ───────────────────────────

def alive_or_dead(next_node):
    """Generic gate: a dead car stops here, a live one moves on."""
    def _fork(state):
        return next_node if state.get("alive") else END
    return _fork


def node_route_note(state: CarState):
    """Records WHY the fork sent this car where it did — the auditable answer to
    'why was this car debated?'"""
    d = dispatch(state["flags"], state["check"], state["estimate"])
    return {"route": d["route"], "route_reason": d["why"],
            "audit": _audit(state, f"fork → {d['route']} ({d['why']})")}


def fork_dispatch(state: CarState):
    """THE fork. Four tripwires, all deterministic."""
    d = dispatch(state["flags"], state["check"], state["estimate"])
    return "defender" if d["route"] == "negotiation" else "rank"


def after_defender(state: CarState):
    return "settle" if ACCEPT_RE.search(state["transcript"][-1]) else "critic"


def after_critic(state: CarState):
    if VERDICT_RE.search(state["transcript"][-1]):
        return "settle"
    return "settle" if state.get("rounds", 0) >= MAX_ROUNDS else "defender"


def after_settle(state: CarState):
    return "rank" if state.get("alive") else END


# ─────────────────────────── wiring ───────────────────────────

def build_graph(checkpointer=None):
    g = StateGraph(CarState)

    for name, fn in [
        ("filters", node_filters), ("landed", node_landed), ("flags", node_flags),
        ("estimate", node_estimate), ("check", node_check), ("route_note", node_route_note),
        ("defender", node_defender), ("critic", node_critic), ("settle", node_settle),
        ("rank", node_rank),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "filters")

    # cheap and deadly first — each rule desk can end the run
    g.add_conditional_edges("filters", alive_or_dead("landed"), ["landed", END])
    g.add_conditional_edges("landed", alive_or_dead("flags"), ["flags", END])
    g.add_edge("flags", "estimate")
    g.add_edge("estimate", "check")
    g.add_conditional_edges("check", alive_or_dead("route_note"), ["route_note", END])

    # the fork
    g.add_conditional_edges("route_note", fork_dispatch, ["defender", "rank"])

    # the negotiation: defender ⇄ critic, either can exit to settle
    g.add_conditional_edges("defender", after_defender, ["critic", "settle"])
    g.add_conditional_edges("critic", after_critic, ["defender", "settle"])
    g.add_conditional_edges("settle", after_settle, ["rank", END])

    g.add_edge("rank", END)

    return g.compile(checkpointer=checkpointer)


def open_graph(db_path="bidwise.sqlite"):
    """Yields a graph with SQLite-backed state that survives restarts."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return build_graph(SqliteSaver(conn)), conn