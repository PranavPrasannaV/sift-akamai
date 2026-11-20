"""Read a case label or a printed recall notice from a photo with VISION_MODEL.

A kitchen worker standing at the walk-in can photograph a case instead of typing
it. gemma-4-26b-a4b-it reads the label into fields; the fields then go through
the same lookups as an inventory line (exact code, then meaning). The model only
transcribes: whether the case is recalled is decided by the corpus, not by it.
"""

from __future__ import annotations

import base64
import json
import re

from pullsheet.akamai import inference

PROMPT = """Transcribe this food case label or recall notice. Reply with JSON only:
{"product": "...", "brand_or_firm": "...", "upc_or_gtin": "...", "lot": "...", "pack_size": "..."}
Copy characters exactly as printed. Use null for anything not visible. Do not guess."""


def data_url(content: bytes, content_type: str | None) -> str:
    return f"data:{content_type or 'image/jpeg'};base64,{base64.b64encode(content).decode()}"


def read_label(content: bytes, content_type: str | None = None) -> dict:
    raw = inference.vision(PROMPT, data_url(content, content_type))
    start, end = raw.find("{"), raw.rfind("}")
    try:
        fields = json.loads(raw[start:end + 1]) if start >= 0 else {}
    except ValueError:
        fields = {}
    fields = {k: (str(v).strip() if v not in (None, "", "null") else None) for k, v in fields.items()}
    code = re.sub(r"\D", "", fields.get("upc_or_gtin") or "")
    fields["digits"] = code or None
    fields["raw"] = raw
    return fields


def exact_code_hits(digits: str | None, recalls: list[dict]) -> list[dict]:
    """Recalls whose code text contains the label's barcode digits (or the last 11,
    since a 12-digit UPC is often printed without its check digit)."""
    if not digits or len(digits) < 8:
        return []
    probes = {digits, digits[-12:], digits[-11:], digits[1:12] if len(digits) >= 12 else digits}
    hits = []
    for r in recalls:
        text = re.sub(r"\D", "", f"{r.get('product_description') or ''} {r.get('code_info') or ''}")
        if any(p and len(p) >= 8 and p in text for p in probes):
            hits.append(r)
    return hits
