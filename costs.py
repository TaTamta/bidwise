# costs.py — pure rules. No models, no side effects: dict in, dict out.

from repo import customs_cost_usd, rates, buyer_profile


def landed_cost(listing):
    """Every cost line from hammer price to cleared-in-Tbilisi, before repairs.

    Returns a full breakdown — the report desk shows these lines to her,
    because 'I can't calculate this myself' is the whole reason this exists.
    """
    r = rates()
    bid = float(listing["current_bid_usd"])

    auction_fee = round(bid * r["auction_fee_pct"], 2)
    freight = r["us_inland_usd"] + r["ocean_freight_usd"]
    port = r["poti_handling_usd"] + r["broker_clearance_usd"]

    customs = customs_cost_usd(
        year=listing["year"],
        engine_l=listing["engine_l"],
        car_value_usd=bid,
        freight_usd=freight,
        hybrid=listing.get("hybrid", False),
        electric=listing.get("electric", False),
    )

    total = bid + auction_fee + freight + port + customs["customs_total_usd"]

    return {
        "bid_usd": round(bid, 2),
        "auction_fee_usd": auction_fee,
        "freight_usd": round(freight, 2),
        "port_usd": round(port, 2),
        "customs": customs,
        "landed_total_usd": round(total, 2),
    }


def early_budget_check(landed, profile=None):
    """The cheap kill: already over budget before repairs are even estimated.

    Silent tier — a car that can't fit the budget without a single repair
    is obvious garbage, and she said she doesn't want to see those.
    """
    p = profile or buyer_profile()
    total = landed["landed_total_usd"]
    ceiling = p["max_total_usd"]

    if total > ceiling:
        return {
            "passed": False,
            "kill_tier": "silent",
            "reason": f"landed cost ${total:,.0f} exceeds ${ceiling:,.0f} before any repairs",
        }

    return {
        "passed": True,
        "kill_tier": None,
        "reason": f"landed ${total:,.0f}, ${ceiling - total:,.0f} under the ceiling", 
        }