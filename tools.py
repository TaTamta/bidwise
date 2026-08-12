# tools.py — the functions the negotiators may reach for mid-argument.
#
# Note what is and isn't here. Rule desks call repo.py directly, because when
# a fetch is unconditional there is no decision for a model to make. These are
# tools because the negotiation genuinely doesn't know in advance what it will
# need to look up — that is when tool use is the right pattern.

from langchain.tools import tool
from repo import (auction_history, market_price, auction_baseline,
                  decode_vin, repair_reference)


@tool
def vin_record(vin: str) -> str:
    """Decode a VIN against the manufacturer's official record (NHTSA vPIC).
    Returns year, make, model, engine size, body class and plant country.
    Use this to check whether the listing describes the car it is actually selling."""
    d = decode_vin(vin)
    if not d:
        return f"vPIC returned nothing for {vin} — the decoder is unavailable or the VIN is not recognised. This is not evidence of anything."
    return (f"VIN {vin}: {d.get('year')} {d.get('make')} {d.get('model')}, "
            f"{d.get('engine_l')}L {d.get('fuel')}, body class {d.get('body_class')}, "
            f"built in {d.get('plant_country')}.")


@tool
def past_auctions(vin: str) -> str:
    """List previous appearances of this VIN at auction, with dates and sale prices.
    Use this to judge whether a car has been bought and thrown back, and how often."""
    past = auction_history(vin)
    if not past:
        return f"No prior auction appearances on record for {vin}."
    return f"{len(past)} prior appearance(s) for {vin}: " + "; ".join(
        f"listed {p['listed_date']}, sold ${p['sold_price_usd']:,}" for p in past)


@tool
def tbilisi_price(make: str, model: str, year: int) -> str:
    """The asking price in Tbilisi for this car cleared, running and repaired.
    Use this to check what the buyer's alternative actually costs locally."""
    p = market_price(make, model, year)
    if not p:
        return f"No Tbilisi comparable on record for a {year} {make} {model}."
    return f"A cleared, running {year} {make} {model} asks about ${p:,} in Tbilisi."


@tool
def auction_norm(make: str, model: str, year: int) -> str:
    """The typical hammer price at US auction for a lightly-damaged, running example.
    Use this to judge whether the current bid is unusually low for the model."""
    b = auction_baseline(make, model, year)
    if not b:
        return f"No auction baseline on record for a {year} {make} {model}."
    return (f"A lightly-damaged, running {year} {make} {model} normally fetches "
            f"about ${b:,} at US auction.")


@tool
def repair_price(work: str) -> str:
    """Look up the Tbilisi shop price range for a specific repair job, e.g.
    'rear bumper', 'frame straightening', 'airbag module'. Use this to check
    whether a claim about repair cost is realistic."""
    ref = repair_reference()
    key = work.strip().lower()
    if key in ref:
        return f"{key}: ${ref[key]['low']}-${ref[key]['high']} in Tbilisi (parts + labor + paint)."
    close = [k for k in ref if key in k or k in key]
    if close:
        return "No exact match. Closest: " + "; ".join(
            f"{k} ${ref[k]['low']}-${ref[k]['high']}" for k in close[:3])
    return f"No reference price for '{work}'. Available jobs: {', '.join(list(ref)[:12])}…"


DEFENDER_TOOLS = [tbilisi_price, auction_norm, repair_price, vin_record]
CRITIC_TOOLS = [past_auctions, auction_norm, vin_record, repair_price, tbilisi_price]