# ranking.py — pure rule. Scores survivors on her stated preference order and
# assembles the shortlist. Soft limits rank a car lower; they never kill it.

from repo import buyer_profile, market_price

# her priority order from the interview, in her words:
# "less damage to fix, fewer owners, lower mileage — in that order"
WEIGHTS = {
    "savings": 40,      # how far under the 85% cap the car lands — the point of the exercise
    "damage": 30,       # less to fix is better (uses the repair estimate)
    "mileage": 20,      # soft limit, ranks down rather than killing
    "extras": 10,       # nice_to_have matches
}


def _savings_score(car):
    """0-1. How much of the potential saving this car actually delivers."""
    chk = car["check"]
    market = market_price(car["listing"]["make"], car["listing"]["model"], car["listing"]["year"])
    if not market or not chk.get("likely_total_usd"):
        return 0.5
    ratio = chk["likely_total_usd"] / market      # lower is better
    # 55% of market or below = perfect; at/above the 85% cap = zero
    return max(0.0, min(1.0, (0.85 - ratio) / 0.30))


def _damage_score(car):
    """0-1. Cheaper repairs score higher. $200 or less = perfect; $4,000+ = zero."""
    likely = car["estimate"].get("likely")
    if likely is None:
        return 0.0
    return max(0.0, min(1.0, (4000 - likely) / 3800))


def _mileage_score(car, profile):
    """0-1. Under the soft limit is full marks, then it decays — never kills."""
    km = car["listing"].get("mileage_km")
    limit = (profile.get("soft_limits") or {}).get("max_mileage_km")
    if km is None:
        return 0.5
    if not limit:
        return max(0.0, min(1.0, (150000 - km) / 150000))
    if km <= limit:
        return 1.0
    over = km - limit
    return max(0.0, 1.0 - over / limit)           # 2x the limit = zero


def _extras_score(car, profile):
    """0-1. Fraction of her nice-to-haves this car satisfies."""
    wants = profile.get("nice_to_have") or []
    if not wants:
        return 0.5
    l = car["listing"]
    blob = " ".join(str(v).lower() for v in l.values())
    hits = 0
    for want in wants:
        w = want.lower()
        if "hybrid" in w:
            hits += 1 if ("hybrid" in blob or l.get("hybrid")) else 0
        elif "white" in w:                       # "not white"
            hits += 0 if "white" in blob else 1
        else:
            hits += 1 if w in blob else 0
    return hits / len(wants)


def score_car(car, profile=None):
    """Returns the weighted score plus the component breakdown, so the report
    can say WHY a car ranked where it did."""
    p = profile or buyer_profile()
    parts = {
        "savings": _savings_score(car),
        "damage": _damage_score(car),
        "mileage": _mileage_score(car, p),
        "extras": _extras_score(car, p),
    }
    total = sum(parts[k] * WEIGHTS[k] for k in WEIGHTS)
    return {"score": round(total, 1), "parts": {k: round(v, 2) for k, v in parts.items()}}


def build_shortlist(cars, profile=None):
    """cars: survivors, each with listing/landed/flags/estimate/check and optionally
    a negotiation result. Returns the ranked top N plus everything that didn't make it."""
    p = profile or buyer_profile()
    scored = []
    for car in cars:
        s = score_car(car, p)
        scored.append({**car, "score": s["score"], "score_parts": s["parts"]})

    scored.sort(key=lambda c: c["score"], reverse=True)
    n = p.get("shortlist_size", 7)
    return {"shortlist": scored[:n], "ranked_out": scored[n:]}