# The ORIGINAL notice design (model writes every item row), kept only as the benchmark baseline.
"""Draft the 24-hour distributor notification, then check it against the database.

USDA gives a school food authority 24 hours to notify its distributor. The pull
sheet already holds every fact the notice needs; what takes a manager time is the
writing. CHAT_MODEL (qwen3-8-27b) writes the prose, one message per distributor.

The model is not trusted with a single number. After drafting, every token in
the draft that contains a digit is looked up in the rows the draft was written
from. For each pulled line the checker confirms that its item code appears, and
that the quantity on the same line of the draft is the quantity in the database.
Anything it cannot trace is listed for a person, and the page says so.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date

from pullsheet.akamai import inference

SYSTEM = (
    "You write short, plain business email for a school kitchen manager. "
    "No Markdown headings, no bold, no tables. Never invent a number, code, phone number, "
    "name, or date: use only what you are given. If something is unknown, leave it out."
)

PROMPT = """/no_think
Write one email from {location} to the distributor {vendor}, notifying them within the
USDA 24-hour window that the kitchen has recalled product on hand and is holding it.
Ask them to arrange pickup or credit and to confirm in writing.

After a two or three sentence opening, list EVERY item below, one per line, exactly in this form:
- <description> | item <item code> | <quantity> <unit> | lot <lot> | recall <recall id>

Copy each code, quantity, lot and recall id character for character. End with a one-line
sign-off from "{location} kitchen manager". Start with a "Subject:" line.

Items ({n}):
{rows}
"""


def _fmt_qty(q) -> str:
    if q is None:
        return "quantity not recorded"
    q = float(q)
    return str(int(q)) if q.is_integer() else f"{q:g}"


def _row_text(line: dict) -> str:
    return (f"- {line['raw_description']} | item {line.get('vendor_item_code') or 'none'} | "
            f"{_fmt_qty(line.get('quantity'))} {line.get('unit') or ''} | "
            f"lot {line.get('lot_code') or 'not recorded'} | recall {line['source_record_id']}"
            f" ({line.get('recalling_firm') or 'firm not named'}, {line.get('classification') or 'unclassified'})")


def by_vendor(lines: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for line in lines:
        groups.setdefault(line.get("vendor_name") or "Unknown distributor", []).append(line)
    return groups


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-./#]*")


def _digit_tokens(text: str) -> list[str]:
    return [t.rstrip(".,;:)") for t in _TOKEN.findall(text) if any(ch.isdigit() for ch in t)]


def verify(draft: str, lines: list[dict], allowed_extra: set[str] = frozenset()) -> dict:
    """Trace every digit-bearing token in the draft back to the source rows."""
    known: set[str] = set(allowed_extra)
    for line in lines:
        for value in line.values():
            if value is None:
                continue
            text = _fmt_qty(value) if isinstance(value, (int, float)) else str(value)
            known.add(text)
            known.update(_digit_tokens(text))
    unverified = sorted({t for t in _digit_tokens(draft) if t not in known})

    draft_lines = draft.splitlines()
    checks, missing = [], []
    for line in lines:
        code = line.get("vendor_item_code")
        recall_id = line["source_record_id"]
        anchor = code or recall_id
        hits = [d for d in draft_lines if anchor and anchor in d and recall_id in d]
        if not hits:
            hits = [d for d in draft_lines if anchor and anchor in d]
        if not hits:
            missing.append(line)
            checks.append({"line": line, "ok": False, "what": f"item {anchor} is not in the draft"})
            continue
        qty = _fmt_qty(line.get("quantity"))
        qty_ok = any(qty in _digit_tokens(h) or (qty == "quantity not recorded" and qty in h)
                     for h in hits)
        lot = line.get("lot_code")
        lot_ok = (not lot) or any(lot in h for h in hits)
        ok = qty_ok and lot_ok
        what = []
        what.append(f"quantity {qty} " + ("matches" if qty_ok else "NOT FOUND on this line"))
        if lot:
            what.append(f"lot {lot} " + ("matches" if lot_ok else "NOT FOUND on this line"))
        checks.append({"line": line, "ok": ok, "what": "; ".join(what), "draft_line": hits[0].strip()})
    return {"checks": checks, "missing": missing, "unverified": unverified,
            "all_ok": not missing and not unverified and all(c["ok"] for c in checks)}


def draft_for_vendor(vendor: str, lines: list[dict], location: str) -> str:
    prompt = PROMPT.format(location=location, vendor=vendor, n=len(lines),
                           rows="\n".join(_row_text(l) for l in lines))
    return inference.chat(SYSTEM, prompt, max_tokens=300 + 70 * len(lines))


def draft_notices(lines: list[dict], location: str, today: date | None = None) -> list[dict]:
    """One drafted and verified email per distributor."""
    today = today or date.today()
    allowed = {"24", "24-hour", "48", "48-hour", today.isoformat(), str(today.year),
               *_digit_tokens(location)}
    from concurrent.futures import ThreadPoolExecutor

    groups = list(by_vendor(lines).items())
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(lambda vg: draft_for_vendor(vg[0], vg[1], location), groups))
    return [{"vendor": vendor, "lines": group, "draft": draft, **verify(draft, group, allowed)}
            for (vendor, group), draft in zip(groups, drafts)]
