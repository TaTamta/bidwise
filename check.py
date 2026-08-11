# check.py — the full check + the fork. Rules only.
# The fork DETECTS uncertainty; it never resolves it. Resolution is the
# negotiation's job. The doorway to judgment must itself be a rule.

from repo import market_price, buyer_profile


def full_check(listing, landed, repair_range, profile=None):
    """Two separate questions:
      - the BUDGET ceiling applies to landed cost (repairs are the buyer's own
        business unless repairs_in_budget is True — she may fix it herself)
      - the SAVINGS rule always includes repairs, because a wrecked car is only
        comparable to a running Tbilisi car once it's fixed
    """
    p = profile or buyer_profile()
    market = market_price(listing["make"], listing["model"], listing["year"])
    ceiling = p["max_total_usd"]
    landed_total = landed["landed_total_usd"]

    # a failed estimate must never look like a free repair
    if not repair_range.get("ok", True) or repair_range.get("likely") is None:
        return {"passed": False, "kill_tier": "explain",
                "reason": "repair estimate unavailable — cannot price this car",
                "likely_total_usd": None, "high_total_usd": None,
                "landed_total_usd": landed_total, "savings_cap_usd": None}

    likely_total = landed_total + repair_range["likely"]
    high_total = landed_total + repair_range["high"]
    savings_cap = market * (1 - p["target_savings_pct"]) if market else None

    base = {"likely_total_usd": likely_total,
            "high_total_usd": high_total,
            "landed_total_usd": landed_total,
            "savings_cap_usd": savings_cap}

    budget_figure = likely_total if p.get("repairs_in_budget") else landed_total
    if budget_figure > ceiling:
        what = "likely all-in" if p.get("repairs_in_budget") else "landed cost"
        return {**base, "passed": False, "kill_tier": "explain",
                "reason": f"{what} ${budget_figure:,.0f} exceeds ${ceiling:,.0f}"}

    if savings_cap and likely_total > savings_cap:
        return {**base, "passed": False, "kill_tier": "explain",
                "reason": f"landed + repairs ${likely_total:,.0f} is over 85% of the "
                          f"${market:,} Tbilisi price — not worth the five months"}

    return {**base, "passed": True, "kill_tier": None,
            "reason": f"landed ${landed_total:,.0f}; with shop-rate repairs "
                      f"${likely_total:,.0f} ({likely_total/market:.0%} of market)"}


def dispatch(flags, check, estimate, profile=None):
    """The fork. Four tripwires, all rules. Any one means
    'reasonable people would argue about this car'."""
    p = profile or buyer_profile()
    reasons = []

    if flags["count"] > 0:
        reasons.append(f"{flags['count']} fraud flag(s)")

    budget_figure = check["high_total_usd"] if p.get("repairs_in_budget") \
        else check["landed_total_usd"]
    if budget_figure and budget_figure > p["max_total_usd"]:
        reasons.append("high-end estimate busts the budget")

    if check.get("savings_cap_usd") and check.get("high_total_usd") \
            and check["high_total_usd"] > check["savings_cap_usd"]:
        reasons.append("high-end estimate erases the 15% saving")

    if estimate.get("confidence") == "low" or not estimate.get("ok", True):
        reasons.append("low-confidence repair estimate")

    if reasons:
        return {"route": "negotiation", "why": "; ".join(reasons)}
    return {"route": "ranked_list", "why": "clean on every tripwire"}