# negotiation.py — the only desk where two agents argue.
# They talk THROUGH the transcript; agents have no telepathy. A rule reads the
# verdict out of what they said. Agents decide in-or-out; rules set the money.

import re
from dotenv import load_dotenv
load_dotenv()

from langchain.chat_models import init_chat_model
from repo import market_price, buyer_profile

MODEL = "anthropic:claude-sonnet-5"
model = init_chat_model(MODEL)

MAX_ROUNDS = 3   # critic turns. Then she decides, rather than looping forever.

# the rule that reads the verdict. MULTILINE so it matches the signal wherever
# in the reply the agent put it — not just at the start.
VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(IN|OUT)\b", re.I | re.M)
ACCEPT_RE = re.compile(r"^\s*ACCEPT\b", re.I | re.M)

DEFENDER_SYSTEM = """You are the BUYER'S DEFENDER in an internal review of a salvage car
from a US auction. Your job is to argue for the car when it deserves it: budget headroom,
saving against the Tbilisi market price, and what the evidence actually shows.

Be honest, not promotional. If the critic raises a real problem — fraud pattern, structural
risk, a repair range that swallows the saving — concede it. You are not a salesman; you exist
so that good cars aren't thrown away by an over-cautious system.

2-3 sentences per turn. If the critic has convinced you the car should be dropped, put the
word ACCEPT alone on its own line (first or last line of your reply)."""

CRITIC_SYSTEM = """You are the RISK CRITIC in an internal review of a salvage car from a US
auction. Your job is to find the reason this car is a trap: fraud flags, what the market may
know that the listing doesn't say, hidden damage the estimator warned about, and the high end
of the repair range.

Be skeptical, not reflexively negative. A cosmetically damaged car with a clean history and
real savings is a good buy, and saying so is part of your job.

2-3 sentences per turn. When you are ready to commit, put your verdict on its own line
(first or last line of your reply), exactly one of:
VERDICT: IN
VERDICT: OUT"""


def case_brief(car):
    """What both negotiators see before every turn. Same facts, opposite jobs."""
    l, landed, flags = car["listing"], car["landed"], car["flags"]
    est, chk = car["estimate"], car["check"]
    market = market_price(l["make"], l["model"], l["year"])

    lines = [
        f"CAR: {l['year']} {l['make']} {l['model']}, {l.get('mileage_km', 0):,} km, "
        f"{l['title_status']} title",
        f"DAMAGE: {l['damage_description']}",
        f"BID NOW: ${l['current_bid_usd']:,.0f}   AUCTION ENDS: {l['auction_end_date']}",
        f"LANDED COST: ${landed['landed_total_usd']:,.0f} "
        f"(bid + ${landed['landed_total_usd'] - landed['bid_usd']:,.0f} fees, freight, customs)",
        f"REPAIRS (Tbilisi shop rates): ${est['low']:,.0f} low / ${est['likely']:,.0f} likely / "
        f"${est['high']:,.0f} high — estimator confidence: {est['confidence']}",
        f"ESTIMATOR'S HIDDEN RISK: {est.get('hidden_risk') or 'none noted'}",
        f"TBILISI MARKET (same car, cleared and running): ${market:,}" if market else "MARKET: unknown",
        f"ALL-IN AT SHOP RATES: ${chk['likely_total_usd']:,.0f} likely / "
        f"${chk['high_total_usd']:,.0f} high   ·   85% SAVINGS CAP: ${chk['savings_cap_usd']:,.0f}",
        f"HER BUDGET: ${buyer_profile()['max_total_usd']:,} on landed cost "
        f"(she may do repairs herself)",
    ]
    if flags["flags"]:
        lines.append("FRAUD FLAGS RAISED BY THE RULES:")
        lines += [f"  - {f}" for f in flags["flags"]]
    else:
        lines.append("FRAUD FLAGS: none")
    lines.append(f"WHY THIS CAR IS BEING DEBATED: {car['route_reason']}")
    return "\n".join(lines)


def _speak(system, brief, transcript, instruction):
    convo = "\n\n".join(transcript) or "(you open the review)"
    prompt = f"{brief}\n\nREVIEW SO FAR:\n{convo}\n\n{instruction}"
    return model.invoke([("system", system), ("user", prompt)]).text.strip()


def negotiate(car, verbose=True):
    """Run the debate. Returns verdict + transcript + a rule-set bid ceiling.

    car = {"listing","landed","flags","estimate","check","route_reason"}
    """
    brief = case_brief(car)
    transcript, rounds = [], 0
    verdict, ended_by = None, None

    while rounds < MAX_ROUNDS:
        # ── defender speaks ──
        text = _speak(DEFENDER_SYSTEM, brief, transcript,
                      "Make your case for this car, or answer the critic's last point.")
        transcript.append(f"DEFENDER: {text}")
        if verbose:
            print(f"\n  🛡  {text}")

        if ACCEPT_RE.search(text):
            verdict, ended_by = "OUT", "defender conceded"
            break

        # ── critic answers ──
        text = _speak(CRITIC_SYSTEM, brief, transcript,
                      "Answer the defender. Commit to a verdict as soon as you can defend one.")
        transcript.append(f"CRITIC: {text}")
        rounds += 1
        if verbose:
            print(f"\n  ⚔  {text}")

        m = VERDICT_RE.search(text)          # rule reads the verdict; it can't be persuaded
        if m:
            verdict, ended_by = m.group(1).upper(), "critic committed"
            break

    if verdict is None:
        verdict, ended_by = "UNDECIDED", f"no verdict after {MAX_ROUNDS} rounds — she decides"

    return {
        "verdict": verdict,
        "ended_by": ended_by,
        "rounds": rounds,
        "transcript": transcript,
        # a deadlocked car still gets a ceiling, but it is NOT a recommendation:
        # the report must label it "ceiling if you decide to proceed".
        "bid_ceiling_usd": bid_ceiling(car) if verdict in ("IN", "UNDECIDED") else None,
        "is_recommendation": verdict == "IN",
    }


def bid_ceiling(car):
    """RULE, not opinion. The highest bid that still keeps landed cost under her
    ceiling and landed + likely repairs under the 85% savings cap.
    Agents argue; rules hold the purse."""
    chk, landed, est = car["check"], car["landed"], car["estimate"]
    p = buyer_profile()
    bid = landed["bid_usd"]

    # everything above the hammer price is treated as fixed overhead — conservative
    overhead = landed["landed_total_usd"] - bid

    caps = [p["max_total_usd"] - overhead]                            # her landed ceiling
    if chk.get("savings_cap_usd"):
        caps.append(chk["savings_cap_usd"] - overhead - est["likely"])  # the 15% saving

    return round(max(0.0, min(caps)), 2)