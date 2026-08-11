# filters.py — pure rules. The cheapest desk, standing at the front door.
# Only HARD requirements live here. Soft preferences belong to the ranking desk.

from repo import buyer_profile


def hard_filters(listing, profile=None):
    """Her dealbreakers. Any failure kills the car silently — she said she
    doesn't want to see obvious garbage."""
    p = profile or buyer_profile()
    fails = []

    if listing["year"] < p["min_year"]:
        fails.append(f"year {listing['year']} is older than {p['min_year']}")

    if listing["body_type"] not in p["body_types"]:
        fails.append(f"body type '{listing['body_type']}' not wanted")

    if p.get("trusted_makes") and listing["make"] not in p["trusted_makes"]:
        fails.append(f"make '{listing['make']}' outside trusted brands")

    if p.get("excluded_makes") and listing["make"] in p["excluded_makes"]:
        fails.append(f"make '{listing['make']}' explicitly excluded")

    if listing["title_status"] in p["excluded_titles"]:
        fails.append(f"{listing['title_status']} title")

    if p.get("transmission") and listing.get("transmission") != p["transmission"]:
        fails.append(f"transmission '{listing.get('transmission')}' — she wants {p['transmission']}")

    if p["no_airbags_deployed"] and listing["airbags_deployed"]:
        fails.append("airbags deployed")

    if p["must_run_and_drive"] and not listing["runs_and_drives"]:
        fails.append("does not run and drive")

    if fails:
        return {"passed": False, "kill_tier": "silent", "reason": "; ".join(fails)}
    return {"passed": True, "kill_tier": None, "reason": "meets all hard requirements"}