# data.py — snapshot mock data. Replace with API calls later (see repo.py).
# NOTE: listings are realistically shaped but invented. VINs are not real, so the
# vPIC cross-check will politely no-op on them. Swap in real listings before demoing.

LISTINGS = {
    "LOT-58412": {  # borderline: low-confidence estimate on a rear hit
        "lot_id": "LOT-58412", "vin": "KNDPMCAC5N7000123",
        "year": 2022, "make": "Kia", "model": "Sportage", "body_type": "SUV",
        "engine_l": 2.4, "transmission": "automatic", "mileage_km": 41000,
        "title_status": "salvage",
        "damage_description": "rear collision: bumper, tailgate, taillight",
        "airbags_deployed": False, "runs_and_drives": True,
        "current_bid_usd": 4200, "auction_end_date": "2026-08-08",
        "location": "Newark, NJ",
    },
    "LOT-61077": {  # dies at filters — flood title
        "lot_id": "LOT-61077", "vin": "5NMJBCAE8NH000456",
        "year": 2022, "make": "Hyundai", "model": "Tucson", "body_type": "SUV",
        "engine_l": 2.5, "transmission": "automatic", "mileage_km": 30000,
        "title_status": "flood",
        "damage_description": "water damage, interior; minor scratch front bumper",
        "airbags_deployed": False, "runs_and_drives": True,
        "current_bid_usd": 4100, "auction_end_date": "2026-08-05",
        "location": "Houston, TX",
    },
    "LOT-59930": {  # dies at filters — airbags deployed, doesn't run
        "lot_id": "LOT-59930", "vin": "JTMRWRFV0ND000789",
        "year": 2021, "make": "Toyota", "model": "RAV4", "body_type": "SUV",
        "engine_l": 2.5, "transmission": "automatic", "mileage_km": 58000,
        "title_status": "salvage",
        "damage_description": "front-end collision, airbags deployed",
        "airbags_deployed": True, "runs_and_drives": False,
        "current_bid_usd": 3900, "auction_end_date": "2026-08-09",
        "location": "Chicago, IL",
    },
    "LOT-62155": {  # the suspicious one — repeat VIN AND priced too low
        "lot_id": "LOT-62155", "vin": "KM8K2CAB4NU000321",
        "year": 2022, "make": "Hyundai", "model": "Kona", "body_type": "SUV",
        "engine_l": 2.0, "transmission": "automatic", "mileage_km": 36000,
        "title_status": "clean",
        "damage_description": "minor scratch, driver door",
        "airbags_deployed": False, "runs_and_drives": True,
        "current_bid_usd": 3600, "auction_end_date": "2026-08-07",
        "location": "Los Angeles, CA",
    },
    "LOT-60488": {  # the clean one — sails through, no review needed
        "lot_id": "LOT-60488", "vin": "3CZRZ2H50PM000654",
        "year": 2023, "make": "Honda", "model": "HR-V", "body_type": "SUV",
        "engine_l": 2.0, "transmission": "automatic", "mileage_km": 22000,
        "title_status": "salvage",
        "damage_description": "hail damage, cosmetic only",
        "airbags_deployed": False, "runs_and_drives": True,
        "current_bid_usd": 3900, "auction_end_date": "2026-08-12",
        "location": "Dallas, TX",
    },
    "LOT-63220": {  # one soft flag, trivial damage, big margin — the defender's best case
        "lot_id": "LOT-63220", "vin": "7MUDAAAG0NV000987",
        "year": 2022, "make": "Toyota", "model": "Corolla Cross", "body_type": "SUV",
        "engine_l": 2.0, "transmission": "automatic", "mileage_km": 28000,
        "title_status": "salvage",
        "damage_description": "minor front bumper scuff, broken left headlight",
        "airbags_deployed": False, "runs_and_drives": True,
        "current_bid_usd": 3100, "auction_end_date": "2026-08-14",
        "location": "Phoenix, AZ",
    },
}

# past appearances at auction, keyed by VIN — the fraud desk reads this
AUCTION_HISTORY = {
    "KM8K2CAB4NU000321": [
        {"listed_date": "2026-04-02", "sold_price_usd": 3400},
    ],
    "JTMRWRFV0ND000789": [
        {"listed_date": "2024-11-18", "sold_price_usd": 5100},  # old enough not to flag
    ],
}

# Tbilisi asking prices for cleared, running examples (USD, rough medians from myauto.ge).
# used by the 85% savings rule — NOT for fraud detection.
MARKET_PRICES = {
    ("Kia", "Sportage", 2022): 16500,
    ("Hyundai", "Tucson", 2022): 17000,
    ("Toyota", "RAV4", 2021): 19500,
    ("Hyundai", "Kona", 2022): 14500,
    ("Honda", "HR-V", 2023): 17800,
    ("Toyota", "Corolla Cross", 2022): 15800,
}

# typical hammer price at US auction for a lightly-damaged, running example (USD).
# a bid far below this means the market may know something the listing doesn't say.
AUCTION_BASELINES = {
    ("Kia", "Sportage", 2022): 6800,
    ("Hyundai", "Tucson", 2022): 7200,
    ("Toyota", "RAV4", 2021): 8000,
    ("Hyundai", "Kona", 2022): 8000,           # clean-title Konas fetch more
    ("Honda", "HR-V", 2023): 7500,
    ("Toyota", "Corolla Cross", 2022): 6900,   # 3100/6900 = 45% → trips the too-cheap flag
}

# typical Tbilisi repair costs (USD) — parts + labor + paint.
# ranges reflect real spread: aftermarket vs OEM, minor vs full replacement.
REPAIR_REFERENCE = {
    "front bumper":     {"low": 180, "high": 420},
    "rear bumper":      {"low": 170, "high": 400},
    "tailgate":         {"low": 320, "high": 780},
    "hood":             {"low": 280, "high": 650},
    "fender":           {"low": 150, "high": 380},
    "door":             {"low": 240, "high": 600},
    "quarter panel":    {"low": 400, "high": 950},
    "roof":             {"low": 500, "high": 1200},

    "headlight":        {"low": 120, "high": 450},
    "taillight":        {"low": 80,  "high": 280},
    "windshield":       {"low": 130, "high": 320},
    "side window":      {"low": 70,  "high": 190},

    "radiator":         {"low": 150, "high": 380},
    "ac condenser":     {"low": 120, "high": 300},
    "suspension arm":   {"low": 90,  "high": 260},
    "airbag module":    {"low": 450, "high": 1100},
    "seatbelt tensioner": {"low": 120, "high": 300},

    "paint per panel":  {"low": 90,  "high": 220},
    "dent repair (pdr)": {"low": 40,  "high": 130},
    "hail damage (full body pdr)": {"low": 600, "high": 1800},
    "interior detail":  {"low": 60,  "high": 180},

    "frame straightening": {"low": 700, "high": 2200},
    "diagnostics + misc": {"low": 80,  "high": 250},
}

RATES = {
    "auction_fee_pct": 0.10,      # buyer fee on hammer price
    "us_inland_usd": 350,         # auction site -> US port
    "ocean_freight_usd": 1350,    # US -> Poti
    "poti_handling_usd": 250,
    "broker_clearance_usd": 300,
    "vat_pct": 0.18,
    "doc_fees_gel": 480,          # fixed documentation
    "gel_per_usd": 2.70,          # FALLBACK only; live rate comes from NBG
}

# her requirements — from the brief and the interview.
# hard fields kill; soft_limits and nice_to_have only affect ranking.
BUYER_PROFILE = {
    "max_total_usd": 14000,
    "min_year": 2021,
    "body_types": ["SUV", "crossover"],
    "trusted_makes": ["Toyota", "Honda", "Hyundai", "Kia"],
    "excluded_makes": [],
    "excluded_titles": ["flood"],
    "transmission": "automatic",
    "no_airbags_deployed": True,
    "must_run_and_drive": True,
    "repairs_in_budget": False,   # she may fix it herself; the ceiling is on landed cost

    "soft_limits": {"max_mileage_km": 60000},
    "nice_to_have": ["hybrid", "not white"],

    "target_savings_pct": 0.15,
    "repeat_listing_window_days": 180,
    "too_cheap_ratio": 0.5,
    "alert_window_hours": 48,
    "shortlist_size": 7,
}