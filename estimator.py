# estimator.py — judgment desk. Reads damage, returns a costed range.
# The rules downstream consume the numbers; they never let the agent
# talk its way past the ceiling.

import json, re
from dotenv import load_dotenv
load_dotenv()

from langchain.chat_models import init_chat_model
from repo import repair_reference

MODEL = "anthropic:claude-sonnet-5"
model = init_chat_model(MODEL)

PROMPT = """You are an estimator at a Tbilisi body shop that repairs cars imported from US
auctions. Read the damage description and produce a cost estimate in USD.

Use ONLY these reference prices (parts + labor + paint, Tbilisi market):
{reference}

Return ONLY a JSON object, no other text:
{{"line_items": [{{"work": "<reference key or short description>",
                  "low": <number>, "high": <number>,
                  "note": "<why this item, one short phrase>"}}],
  "hidden_risk": "<what a photo-based estimate could be missing, one sentence>",
  "confidence": "high"|"medium"|"low"}}

Rules:
- A rear collision usually damages more than the listing names: check for tailgate alignment,
  quarter panel, and always include paint for each panel touched.
- Include "diagnostics + misc" on every estimate.
- If the damage description suggests possible hidden structural damage, say so in hidden_risk
  and lower confidence — do NOT silently inflate the numbers.
- Stay inside the reference ranges for known work. For work not in the reference, estimate
  conservatively and name it clearly.
- Never return a single number where a range belongs. low < high on every line.

DAMAGE DESCRIPTION: {damage}
CAR: {year} {make} {model}, {mileage_km:,} km, title: {title}
"""


def estimate_repairs(listing):
    """Damage description -> costed range with line items.

    Returns {"low","likely","high","line_items","hidden_risk","confidence"}.
    'likely' is computed by RULE (midpoint), never asked of the model —
    an agent that picks its own headline number will pick a flattering one.
    """
    ref = "\n".join(f"  {k}: ${v['low']}-${v['high']}" for k, v in repair_reference().items())
    prompt = PROMPT.format(
        reference=ref,
        damage=listing.get("damage_description", "unspecified"),
        year=listing["year"], make=listing["make"], model=listing["model"],
        mileage_km=listing.get("mileage_km") or 0,
        title=listing.get("title_status", "unknown"),
    )

    try:
        raw = model.invoke(prompt).text
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))

        items = []
        for it in data.get("line_items", []):
            low, high = float(it["low"]), float(it["high"])
            if low > high:
                low, high = high, low          # the model got them backwards
            items.append({"work": str(it["work"]), "low": low, "high": high,
                          "note": str(it.get("note", ""))})

        if not items:
            raise ValueError("no line items returned")

        low = round(sum(i["low"] for i in items), 2)
        high = round(sum(i["high"] for i in items), 2)
        likely = round((low + high) / 2, 2)     # RULE, not the agent's opinion

        return {"ok": True, "low": low, "likely": likely, "high": high,
                "line_items": items,
                "hidden_risk": data.get("hidden_risk", ""),
                "confidence": str(data.get("confidence", "low")).lower(),
                "note": f"{len(items)} line item(s), ${low:,.0f}–${high:,.0f}"}

    except Exception as e:
        # a failed estimate must not become a cheap estimate
        return {"ok": False, "low": None, "likely": None, "high": None,
                "line_items": [], "hidden_risk": "estimate failed",
                "confidence": "none", "note": f"ESTIMATE FAILED — route to human ({e})"}