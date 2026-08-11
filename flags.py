# flags.py — pure rules. Detects suspicion; interpretation happens later,
# in the negotiation. Rule detects, judgment interprets.

from datetime import date
from repo import auction_history, auction_baseline, buyer_profile, decode_vin


def _vin_mismatches(listing):
    """Compare the listing's claims against the manufacturer's own record.
    A mismatch isn't proof of fraud — but customs is computed from engine size,
    so a wrong engine is a wrong landed cost."""
    d = decode_vin(listing["vin"])
    if not d or str(d.get("error_code") or "0").split(",")[0] not in ("0", "None"):
        return []          # decoder unavailable or VIN unrecognised — never a flag

    out = []
    if d.get("year") and d["year"] != listing["year"]:
        out.append(f"listing says {listing['year']}, the VIN decodes to {d['year']}")

    if d.get("make") and listing["make"].lower() not in d["make"].lower():
        out.append(f"listing says {listing['make']}, the VIN decodes to {d['make']}")

    if d.get("engine_l") and listing.get("engine_l"):
        if abs(d["engine_l"] - listing["engine_l"]) > 0.15:
            out.append(f"listing says {listing['engine_l']}L, the VIN decodes to "
                       f"{d['engine_l']}L — customs is calculated on engine size")

    return out


def fraud_flags(listing, profile=None, today=None):
    """Her two 'too good to be true' patterns, plus a VIN cross-check."""
    p = profile or buyer_profile()
    today = today or date.today()
    flags = []

    # 1. same VIN back at auction within the window
    for past in auction_history(listing["vin"]):
        days = (today - date.fromisoformat(past["listed_date"])).days
        if 0 <= days <= p["repeat_listing_window_days"]:
            flags.append(
                f"same VIN listed {days} days ago ({past['listed_date']}, "
                f"sold ${past['sold_price_usd']:,}) — bought and thrown back?"
            )

    # 2. bid far below what this model normally fetches at auction
    baseline = auction_baseline(listing["make"], listing["model"], listing["year"])
    if baseline:
        ratio = listing["current_bid_usd"] / baseline
        if ratio < p["too_cheap_ratio"]:
            flags.append(
                f"bid is {ratio:.0%} of the ~${baseline:,} this model normally fetches "
                f"at auction — the market may know something the listing doesn't say"
            )

    # 3. does the listing match the manufacturer's own record?
    for mismatch in _vin_mismatches(listing):
        flags.append(f"VIN mismatch: {mismatch}")

    return {"flags": flags, "count": len(flags)}