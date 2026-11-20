"""The AI pages. Mount with `app.include_router(router)` in pullsheet/app.py.

    GET  /ai/second-look   meaning-based neighbours the matcher did not pair
    GET  /ai/notice        the 24-hour distributor notice: explains, offers a button
    POST /ai/notice        drafts one email per distributor and checks every number
    GET  /ai/benchmark     baseline against the AI techniques, from data/benchmark.json
    GET  /ai/label         photograph a case label
    POST /ai/label         read it with the vision model and look it up

Every page labels its output as AI, and none of them writes to `matches` or
`decisions`. A person still decides every line.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from pullsheet import db
from pullsheet.akamai import data, inference

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai")
MAX_IMAGE = 6_000_000


def _templates():
    from pullsheet.app import templates  # lazy: app.py imports this module

    return templates


def _render(request: Request, name: str, context: dict, status_code: int = 200):
    context = {"request": request, "models": {
        "chat": os.environ.get("CHAT_MODEL"), "embedding": os.environ.get("EMBEDDING_MODEL"),
        "vision": os.environ.get("VISION_MODEL")}, **context}
    return _templates().TemplateResponse(name, context, status_code=status_code)


def _problem(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error).strip().splitlines()[0][:200] if str(error).strip() else ''}"


@router.get("/second-look", response_class=HTMLResponse)
def second_look_page(request: Request):
    from pullsheet.akamai import semantic

    conn = db.connect()
    try:
        run = db.latest_ok_run(conn)
        if run is None:
            return _render(request, "ai_second_look.html", {"run": None})
        inventory, recalls = data.active_inventory(conn), data.active_recalls(conn)
        pairs = data.matched_pairs(conn, run["id"])
    finally:
        conn.close()
    context = {"run": run, "inventory_count": len(inventory), "recall_count": len(recalls),
               "pair_count": len(pairs), "retrieve_distance": semantic.RETRIEVE_DISTANCE}
    if not inference.configured() or not os.environ.get("PGHOST"):
        context["error"] = "Akamai Inference or PostgreSQL is not configured on this server."
        return _render(request, "ai_second_look.html", context)
    try:
        context["result"] = semantic.reviewed_second_look(inventory, recalls, pairs)
    except Exception as error:  # noqa: BLE001 -- the page explains rather than 500s
        log.exception("second look failed")
        context["error"] = _problem(error)
    return _render(request, "ai_second_look.html", context)


@router.get("/triage", response_class=HTMLResponse)
def triage_page(request: Request):
    """HELD lines in the order a person should read them. Reorders; never clears."""
    from pullsheet.akamai import semantic

    conn = db.connect()
    try:
        run = db.latest_ok_run(conn)
        if run is None:
            return _render(request, "ai_triage.html", {"run": None})
        held, recalls = data.held_lines(conn, run["id"]), data.active_recalls(conn)
        from pullsheet.matching.run import ordered_matches
        sheet = [r["id"] for r in ordered_matches(conn, run["id"]) if r["status"] == "HELD"]
        base_rank = {m: i + 1 for i, m in enumerate(sheet)}
    finally:
        conn.close()
    context = {"run": run, "read_top": semantic.READ_TOP}
    if not inference.configured() or not os.environ.get("PGHOST"):
        context["error"] = "Akamai Inference or PostgreSQL is not configured on this server."
        return _render(request, "ai_triage.html", context)
    try:
        context["result"] = semantic.triage_held(held, recalls, base_rank=base_rank)
    except Exception as error:  # noqa: BLE001 -- the page explains rather than 500s
        log.exception("triage failed")
        context["error"] = _problem(error)
    return _render(request, "ai_triage.html", context)


@router.get("/benchmark", response_class=HTMLResponse)
def benchmark_page(request: Request):
    """Results written by scripts/benchmark.py: baseline against each technique."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "data" / "benchmark.json"
    bench = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return _render(request, "ai_benchmark.html", {"bench": bench})


def _pull_context(conn):
    run = db.latest_ok_run(conn)
    lines = data.pull_lines(conn, run["id"]) if run else []
    return run, lines


@router.get("/notice", response_class=HTMLResponse)
def notice_page(request: Request):
    from pullsheet.akamai import notice

    conn = db.connect()
    try:
        run, lines = _pull_context(conn)
    finally:
        conn.close()
    return _render(request, "ai_notice.html", {
        "run": run, "lines": lines, "groups": notice.by_vendor(lines), "notices": None})


@router.post("/notice", response_class=HTMLResponse)
def notice_draft(request: Request):
    from pullsheet import location
    from pullsheet.akamai import notice

    conn = db.connect()
    try:
        run, lines = _pull_context(conn)
    finally:
        conn.close()
    context = {"run": run, "lines": lines, "groups": notice.by_vendor(lines), "notices": None}
    if run and lines:
        try:
            context["notices"] = notice.draft_notices(lines, location.NAME)
        except Exception as error:  # noqa: BLE001
            log.exception("notice draft failed")
            context["error"] = _problem(error)
    return _render(request, "ai_notice.html", context)


@router.get("/label", response_class=HTMLResponse)
def label_page(request: Request):
    return _render(request, "ai_label.html", {"fields": None})


@router.post("/label", response_class=HTMLResponse)
async def label_read(request: Request, file: UploadFile = File(...)):
    from pullsheet.akamai import semantic, vision

    content = await file.read(MAX_IMAGE + 1)
    if len(content) > MAX_IMAGE:
        return _render(request, "ai_label.html", {"fields": None, "error": "Images are limited to 6 MB."},
                       status_code=413)
    if not (file.content_type or "").startswith("image/"):
        return _render(request, "ai_label.html", {"fields": None, "error": "Upload a photo (JPEG or PNG)."},
                       status_code=415)
    context: dict = {"fields": None, "filename": file.filename}
    try:
        fields = vision.read_label(content, file.content_type)
        context["fields"] = fields
        conn = db.connect()
        try:
            recalls = data.active_recalls(conn)
        finally:
            conn.close()
        context["code_hits"] = vision.exact_code_hits(fields.get("digits"), recalls)
        described = " ".join(x for x in (fields.get("product"), fields.get("brand_or_firm"),
                                         fields.get("pack_size")) if x)
        if described:
            item = {"id": -1, "raw_description": fields.get("product") or described,
                    "brand": fields.get("brand_or_firm"), "manufacturer": None}
            context["review"] = semantic.reviewed_second_look([item], recalls, set(), k=3)
            context["described"] = semantic.inventory_text(item)
    except Exception as error:  # noqa: BLE001
        log.exception("label read failed")
        context["error"] = _problem(error)
    return _render(request, "ai_label.html", context)
