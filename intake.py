# intake.py — the two judgment desks at the front door.
# R1's trick: judgment reads the mess, code validates AND normalizes the form.
# An agent may guess wrong, but it can never hand the pipeline a malformed
# dict — or a value the rule desks can't match on.

import json, re
from dotenv import load_dotenv
load_dotenv()

from langchain.chat_models import init_chat_model

MODEL = "anthropic:claude-sonnet-5"
model = init_chat_model(MODEL)

# ─────────────────────── canonical vocabularies ───────────────────────
# rule desks match on exact strings, so intake must speak their language.

BODY_TYPES = {"suv": "SUV", "crossover": "SUV", "cuv": "SUV",
              "sedan": "sedan", "hatchback": "hatchback", "wagon": "wagon",
              "pickup": "pickup", "truck": "pickup", "van": "van", "minivan": "van"}

TITLES = {"clean": "clean", "salvage": "salvage", "flood": "flood",
          "water": "flood", "rebuilt": "rebuilt", "lemon": "lemon"}

GERMAN_MAKES = ["BMW", "Mercedes-Benz", "Audi", "Volkswagen", "Porsche", "Opel", "Mini"]

TRIM_NOISE = re.compile(
    r"\b(LX|EX|SE|LE|XLE|XSE|SEL|SPORT|LIMITED|PREMIUM|TOURING|BASE|"
    r"AWD|FWD|RWD|4WD|4X4|2WD|HYBRID|PLUG-?IN)\b", re.I)


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in reply")
    return json.loads(match.group(0))


def _norm_make(value):
    if not value:
        return None
    v = str(value).strip().title()
    return {"Bmw": "BMW", "Gmc": "GMC", "Mercedes Benz": "Mercedes-Benz"}.get(v, v)


def _norm_model(value):
    """Base model only — 'SPORTAGE LX AWD' -> 'Sportage'."""
    if not value:
        return None
    v = TRIM_NOISE.sub("", str(value)).strip()
    v = re.sub(r"\s+", " ", v)
    return v.title() if v else None


def _norm_body(value):
    return BODY_TYPES.get(str(value or "").strip().lower(), "other")


def _norm_title(value):
    return TITLES.get(str(value or "").strip().lower(), "unknown")


def _norm_transmission(value):
    v = str(value or "").strip().lower()
    if v.startswith("auto"):
        return "automatic"
    if v.startswith("man"):
        return "manual"
    return None


# ─────────────────────── 1. her brief → requirements ───────────────────────

BRIEF_PROMPT = """You are an intake clerk for a car-buying service. Read the buyer's message
and return ONLY a JSON object, no other text:

{"max_total_usd": <number>, "min_year": <number>, "body_types": [...],
 "trusted_makes": [...], "excluded_makes": [...],
 "excluded_titles": [...], "transmission": "automatic"|"manual"|null,
 "no_airbags_deployed": <bool>, "must_run_and_drive": <bool>,
 "soft_limits": {"max_mileage_km": <number or null>},
 "nice_to_have": ["soft preferences that are NOT hard requirements"],
 "notes": "anything important that doesn't fit above"}

Rules:
- max_total_usd is the ALL-IN budget (shipping, customs, repairs) unless clearly stated otherwise.
- body_types must use ONLY: SUV, sedan, hatchback, wagon, pickup, van. Treat crossover/CUV as SUV.
- excluded_makes must be actual brand names. If the buyer excludes a category such as
  "German cars", expand it into brands.
- excluded_titles must use ONLY: clean, salvage, flood, rebuilt, lemon.
- Hedged limits ("ideally under 60,000 km", "preferably low mileage") are SOFT: put the number
  in soft_limits. Only an absolute limit ("never over 80,000 km") counts as hard.
- transmission: only fill if the buyer states it explicitly.
- must_run_and_drive: default TRUE unless the buyer explicitly accepts a non-running car.
- no_airbags_deployed: default TRUE unless the buyer explicitly accepts deployed airbags.
- If something isn't stated, use null or an empty list — never invent a requirement.

BUYER'S MESSAGE:
"""


def intake_brief(text):
    """Free-text brief -> validated, normalized requirements form.

    Distinguishes MALFORMED (no JSON, unparseable — a real failure) from
    INCOMPLETE (she didn't state a budget or a year — perfectly normal, and
    the answer is to ask her, not to crash).
    """
    try:
        raw = model.invoke(BRIEF_PROMPT + text).text
        f = _extract_json(raw)

        # what she never told us — collected, not fatal
        missing = []
        if f.get("max_total_usd") is None:
            missing.append("budget")
        if f.get("min_year") is None:
            missing.append("minimum year")
        if not (f.get("body_types") or []):
            missing.append("body type")

        f["max_total_usd"] = float(f["max_total_usd"]) if f.get("max_total_usd") is not None else None
        f["min_year"] = int(f["min_year"]) if f.get("min_year") is not None else None

        f["body_types"] = sorted({_norm_body(b) for b in (f.get("body_types") or [])} - {"other"})
        f["trusted_makes"] = [_norm_make(m) for m in (f.get("trusted_makes") or []) if m]
        f["excluded_titles"] = sorted({_norm_title(t) for t in (f.get("excluded_titles") or [])} - {"unknown"})
        f["nice_to_have"] = list(f.get("nice_to_have") or [])
        f["transmission"] = _norm_transmission(f.get("transmission"))

        excluded = []
        for m in (f.get("excluded_makes") or []):
            if "german" in str(m).lower():
                excluded.extend(GERMAN_MAKES)
            else:
                excluded.append(_norm_make(m))
        f["excluded_makes"] = sorted(set(x for x in excluded if x))

        soft = f.get("soft_limits") or {}
        f["soft_limits"] = {
            "max_mileage_km": int(soft["max_mileage_km"])
            if soft.get("max_mileage_km") is not None else None
        }

        # safety defaults point at caution, not permissiveness
        f["no_airbags_deployed"] = bool(f.get("no_airbags_deployed", True))
        f["must_run_and_drive"] = bool(f.get("must_run_and_drive", True))

        budget = f"${f['max_total_usd']:,.0f}" if f["max_total_usd"] is not None else "not stated"
        year = f"{f['min_year']}+" if f["min_year"] is not None else "year not stated"
        note = (f"extracted budget {budget}, {year}, "
                f"{len(f['trusted_makes'])} trusted make(s), "
                f"{len(f['nice_to_have'])} soft preference(s)")
        if missing:
            note += f" — INCOMPLETE, needs from her: {', '.join(missing)}"

        return {"ok": True, "form": f, "missing": missing, "complete": not missing, "note": note}

    except Exception as e:
        # malformed, not merely incomplete
        return {"ok": False, "form": None, "missing": None, "complete": False,
                "note": f"EXTRACTION FAILED — route to human ({e})"}

# ─────────────────────── 2. raw listing text → listing ───────────────────────

LISTING_PROMPT = """You are an intake clerk reading a raw car auction listing. Return ONLY a
JSON object, no other text:

{"vin": "...", "year": <number>, "make": "...", "model": "...",
 "body_type": "SUV"|"sedan"|"hatchback"|"wagon"|"pickup"|"van",
 "engine_l": <number>, "transmission": "automatic"|"manual"|null,
 "mileage_km": <number>,
 "title_status": "clean"|"salvage"|"flood"|"rebuilt"|"lemon",
 "damage_description": "one short phrase", "airbags_deployed": <bool>,
 "runs_and_drives": <bool>, "current_bid_usd": <number>,
 "auction_end_date": "YYYY-MM-DD", "location": "...",
 "extraction_confidence": "high"|"medium"|"low"}

Rules:
- model must be the BASE model name only. "SPORTAGE LX AWD" -> "Sportage".
  Strip trim levels (LX, EX, SE, XLE, Limited...) and drivetrain (AWD, FWD, 4X4...).
- make must be the brand only, normally capitalised: "KIA" -> "Kia".
- Convert miles to kilometres (1 mi = 1.609 km). mileage_km is always kilometres.
- If the listing mentions water, flood, or hurricane damage, title_status is "flood"
  regardless of what the title line says.
- transmission: US auction listings are automatic unless stated otherwise; use null only if
  genuinely ambiguous.
- runs_and_drives: only true if the listing states it. If unstated, use false and set
  extraction_confidence to "low" — never assume a damaged car drives.
- Never guess a VIN. If a field is genuinely absent use null and lower the confidence.

LISTING:
"""

REQUIRED = ("vin", "year", "make", "model", "current_bid_usd")


def intake_listing(text):
    """Raw listing text -> validated, normalized listing dict shaped like data.py entries."""
    try:
        raw = model.invoke(LISTING_PROMPT + text).text
        c = _extract_json(raw)

        missing = [f for f in REQUIRED if not c.get(f)]
        if missing:
            raise ValueError(f"missing required field(s): {missing}")

        c["make"] = _norm_make(c["make"])
        c["model"] = _norm_model(c["model"])
        c["body_type"] = _norm_body(c.get("body_type"))
        c["title_status"] = _norm_title(c.get("title_status"))
        c["transmission"] = _norm_transmission(c.get("transmission")) or "automatic"

        c["year"] = int(c["year"])
        c["current_bid_usd"] = float(c["current_bid_usd"])
        c["mileage_km"] = int(c["mileage_km"]) if c.get("mileage_km") is not None else None
        c["engine_l"] = float(c["engine_l"]) if c.get("engine_l") is not None else None
        c["airbags_deployed"] = bool(c.get("airbags_deployed", True))    # safe default
        c["runs_and_drives"] = bool(c.get("runs_and_drives", False))     # safe default
        c["lot_id"] = c.get("lot_id") or f"PARSED-{str(c['vin'])[-6:]}"
        c["extraction_confidence"] = str(c.get("extraction_confidence", "low")).lower()

        return {"ok": True, "listing": c,
                "note": f"parsed {c['year']} {c['make']} {c['model']} @ "
                        f"${c['current_bid_usd']:,.0f} (confidence: {c['extraction_confidence']})"}
    except Exception as e:
        return {"ok": False, "listing": None, "note": f"EXTRACTION FAILED — route to human ({e})"}