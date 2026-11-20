"""Draft the 24-hour distributor notification. The model writes no data.

USDA gives a school food authority 24 hours to notify its distributor. The pull
sheet already holds every fact the notice needs; what takes a manager time is the
writing. So the work is split by what each side can be trusted with:

- The ITEM TABLE (product, item code, quantity, lot, recall number, firm, class)
  and the REQUESTED ACTION are built by code, straight from the database rows.
  They cannot be wrong in a way the database is not.
- CHAT_MODEL (qwen3-8-27b) writes only the subject line, a short opening and a
  closing, and is given no product data to repeat.
- The checker then confirms the model's text adds nothing of its own: no digit,
  no item, lot or recall code, no product name, and no action word (destroy,
  discard, return...) that would contradict the fixed request. Anything found is
  listed and the draft is marked "check before sending".

Nothing is sent. A person reads the email and sends it.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date

from pullsheet.akamai import inference

SYSTEM = (
    "You write short, plain business email for a school kitchen manager. "
    "No Markdown, no lists, no tables. Write no numbers, dates, codes, product names, "
    "phone numbers or instructions: the item table and the request are added for you."
)

PROMPT = """/no_think
Write the wording around a recall notification email from {location} to its distributor {vendor}.
A table of the recalled items and a fixed request are inserted by the system between your
OPENING and your CLOSING. Do not describe the items or the request yourself.

Return exactly three parts, each on its own line, prefixed like this:
SUBJECT: <a short subject line about a USDA recall notification>
OPENING: <two short sentences: we are notifying you of recalled product on hand at our kitchen, listed below>
CLOSING: <one or two sentences thanking them and asking them to reply to confirm>
"""

# Fixed text, written by code. The model never writes the request.
REQUEST = ("Requested action: we are holding these cases out of service. Please arrange "
           "pickup or credit, and confirm in writing.")

# Words that would change what the distributor is asked to do.
ACTION_WORDS = ("destroy", "discard", "dispose", "throw", "dump", "return to", "ship back",
                "resell", "serve", "use up", "donate", "keep using")


def _fmt_qty(q) -> str:
    if q is None:
        return "not recorded"
    q = float(q)
    return str(int(q)) if q.is_integer() else f"{q:g}"


def by_vendor(lines: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for line in lines:
        groups.setdefault(line.get("vendor_name") or "Unknown distributor", []).append(line)
    return groups


def item_table(lines: list[dict]) -> str:
    """The data part of the email, built from the database rows only."""
    head = ("Product", "Item code", "Quantity", "Lot", "Recall", "Recalling firm", "Class")
    rows = [(l["raw_description"], l.get("vendor_item_code") or "none",
             f"{_fmt_qty(l.get('quantity'))} {l.get('unit') or ''}".strip(),
             l.get("lot_code") or "not recorded", l["source_record_id"],
             l.get("recalling_firm") or "not named", l.get("classification") or "unclassified")
            for l in lines]
    widths = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]

    def fmt(r):
        return "  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip()

    return "\n".join([fmt(head), fmt(tuple("-" * w for w in widths)), *map(fmt, rows)])


def _parts(raw: str) -> dict[str, str]:
    out = {"SUBJECT": "", "OPENING": "", "CLOSING": ""}
    current = None
    for line in raw.splitlines():
        m = re.match(r"\s*\**(SUBJECT|OPENING|CLOSING)\**\s*:\s*(.*)", line, re.I)
        if m:
            current = m.group(1).upper()
            out[current] = m.group(2).strip()
        elif current and line.strip():
            out[current] = (out[current] + " " + line.strip()).strip()
    return out


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-./#]*")


def verify_prose(prose: str, lines: list[dict], allowed: set[str]) -> list[str]:
    """Everything in the model's own words that carries data or an instruction."""
    found = []
    for tok in _TOKEN.findall(prose):
        tok = tok.rstrip(".,;:)")
        if any(ch.isdigit() for ch in tok) and tok not in allowed:
            found.append(f"number or code {tok!r}")
    low = prose.lower()
    for line in lines:
        for value in (line.get("vendor_item_code"), line.get("lot_code"), line.get("source_record_id")):
            if value and str(value).lower() in low:
                found.append(f"code {value!r}")
        words = re.findall(r"[a-z]{5,}", (line.get("raw_description") or "").lower())
        if words and all(w in low for w in words[:2]):
            found.append(f"product {line['raw_description']!r}")
    for word in ACTION_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low):
            found.append(f"instruction {word!r}")
    return sorted(set(found))


def draft_for_vendor(vendor: str, lines: list[dict], location: str, allowed: set[str]) -> dict:
    raw = inference.chat(SYSTEM, PROMPT.format(location=location, vendor=vendor), max_tokens=260)
    parts = _parts(raw)
    subject = parts["SUBJECT"] or "USDA recall notification"
    opening = parts["OPENING"] or "We are notifying you of recalled product on hand at our kitchen."
    closing = parts["CLOSING"] or "Please reply to confirm."
    added = verify_prose(" ".join((subject, opening, closing)), lines, allowed)
    draft = "\n".join([
        f"Subject: {subject}", "", f"Dear {vendor},", "", opening, "",
        item_table(lines), "", REQUEST, "", closing, "", f"{location} kitchen manager"])
    checks = [{"line": l, "ok": True, "what": "row taken from the database, not written by the model"}
              for l in lines]
    return {"vendor": vendor, "lines": lines, "draft": draft, "checks": checks, "missing": [],
            "unverified": added, "all_ok": not added}


def draft_notices(lines: list[dict], location: str, today: date | None = None) -> list[dict]:
    """One email per distributor: database table, fixed request, model-written wording."""
    allowed = {"24", "24-hour", "USDA"}
    from concurrent.futures import ThreadPoolExecutor

    groups = list(by_vendor(lines).items())
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda vg: draft_for_vendor(vg[0], vg[1], location, allowed), groups))
