# repo.py — the ONLY file that knows where data comes from.
# Later: swap these bodies for calls to your own FastAPI. Nothing downstream changes.

import json, os, requests
from data import (LISTINGS, AUCTION_HISTORY, MARKET_PRICES, AUCTION_BASELINES,
                  REPAIR_REFERENCE, RATES, BUYER_PROFILE)

# ─────────────────────────── data accessors ───────────────────────────

def get_listings():
    return list(LISTINGS.values())

def get_listing(lot_id):
    return LISTINGS.get(lot_id)

def auction_history(vin):
    return AUCTION_HISTORY.get(vin, [])

def market_price(make, model, year):
    return MARKET_PRICES.get((make, model, year))

def auction_baseline(make, model, year):
    return AUCTION_BASELINES.get((make, model, year))

def repair_reference():
    return REPAIR_REFERENCE

def rates():
    return RATES

def buyer_profile():
    return BUYER_PROFILE

# ─────────────────────────── FX (National Bank of Georgia) ───────────────────────────

NBG_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/calculator/"
_fx_cache = {}

def gel_per_usd():
    """Live NBG rate, cached per run. Falls back to the pinned rate in RATES."""
    if "rate" in _fx_cache:
        return _fx_cache["rate"]
    try:
        r = requests.get(NBG_URL, params={"codeFrom": "USD", "codeTo": "GEL", "quantity": 1},
                         timeout=5)
        r.raise_for_status()
        data = r.json()
        rate = float(data["quantity"]) if isinstance(data, dict) else float(data)
        _fx_cache["rate"] = rate
        return rate
    except Exception:
        return RATES["gel_per_usd"]

# ─────────────────────────── customs (rs.ge) ───────────────────────────

RS_URL = "https://www.rs.ge/RsGe.Module/CarClearance/Calculate"
_CACHE_FILE = "customs_cache.json"
_cache = json.load(open(_CACHE_FILE, encoding="utf-8")) if os.path.exists(_CACHE_FILE) else {}

# offline fallback: excise is linear per cm3; 2023/2.9L returned 0.6 GEL/cm3
_EXCISE_GEL_PER_CC = 0.6
_DUTY_PCT_OF_EXCISE = 0.0958   # 166.75 / 1740, observed

def _fallback_customs(engine_l):
    excise = round(engine_l * 1000 * _EXCISE_GEL_PER_CC, 2)
    duty = round(excise * _DUTY_PCT_OF_EXCISE, 2)
    return {"Aqcizi": str(excise), "Sabgad": str(duty),
            "sum": str(round(excise + duty, 2)), "_source": "fallback"}

def customs_raw(year, engine_l, hybrid=False, electric=False,
                right_wheel=False, sport=False, classic=False):
    """Raw rs.ge response: Aqcizi (excise), Sabgad (customs duty), sum — GEL, as strings."""
    key = f"{year}|{engine_l}|{hybrid}|{electric}|{right_wheel}|{sport}|{classic}"
    if key in _cache:
        return _cache[key]

    params = {
        "Celi": year, "Zravismoculoba": engine_l,
        "hybridCar": str(hybrid).lower(), "elektroCar": str(electric).lower(),
        "sWheel": str(right_wheel).lower(), "SportCar": str(sport).lower(),
        "ClassicCar": str(classic).lower(),
    }
    try:
        r = requests.post(RS_URL, params=params, timeout=6)
        r.raise_for_status()
        result = r.json()
        _cache[key] = result
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        return result
    except Exception:
        return _fallback_customs(engine_l)

def customs_cost_usd(year, engine_l, car_value_usd, freight_usd, **kw):
    """Full customs line in USD: excise + duty + VAT + fixed documentation fees.
    VAT base = car value + freight + excise + duty. Returns a breakdown —
    the report desk shows these lines to her."""
    r = customs_raw(year, engine_l, **kw)
    g = gel_per_usd()

    excise_usd = float(r["Aqcizi"]) / g
    duty_usd = float(r["Sabgad"]) / g
    docs_usd = RATES["doc_fees_gel"] / g

    vat_base = car_value_usd + freight_usd + excise_usd + duty_usd
    vat_usd = RATES["vat_pct"] * vat_base

    total = excise_usd + duty_usd + vat_usd + docs_usd
    return {
        "excise_usd": round(excise_usd, 2),
        "duty_usd": round(duty_usd, 2),
        "vat_usd": round(vat_usd, 2),
        "docs_usd": round(docs_usd, 2),
        "customs_total_usd": round(total, 2),
        "source": r.get("_source", "rs.ge"),
    }

# ─────────────────────────── VIN decode (NHTSA vPIC) ───────────────────────────
# Free, official, no API key. Decodes the manufacturer's own specs from a VIN,
# which lets us catch a listing that misdescribes the car it is selling.

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
_VIN_CACHE_FILE = "vin_cache.json"
_vin_cache = json.load(open(_VIN_CACHE_FILE, encoding="utf-8")) \
    if os.path.exists(_VIN_CACHE_FILE) else {}

def decode_vin(vin):
    """Manufacturer specs straight from the VIN. Returns {} if unavailable —
    an unreachable decoder must never look like a mismatch."""
    vin = str(vin).strip().upper()
    if vin in _vin_cache:
        return _vin_cache[vin]

    try:
        r = requests.get(VPIC_URL.format(vin=vin), timeout=6)
        r.raise_for_status()
        row = (r.json().get("Results") or [{}])[0]

        decoded = {
            "make": (row.get("Make") or "").title() or None,
            "model": (row.get("Model") or "").title() or None,
            "year": int(row["ModelYear"]) if row.get("ModelYear") else None,
            "engine_l": float(row["DisplacementL"]) if row.get("DisplacementL") else None,
            "body_class": row.get("BodyClass") or None,
            "fuel": row.get("FuelTypePrimary") or None,
            "plant_country": row.get("PlantCountry") or None,
            "error_code": row.get("ErrorCode"),
        }
        _vin_cache[vin] = decoded
        with open(_VIN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_vin_cache, f, ensure_ascii=False, indent=2)
        return decoded
    except Exception:
        return {}