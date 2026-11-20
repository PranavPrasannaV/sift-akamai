"""Benchmark: baseline vs what we built, on the committed ground truth.

1. Held-line reading order. data/fixtures/expected_matches.json lists 30 inventory
   rows that truly match a named recall. Sift is allowed to HOLD a true match rather
   than pull it, and those true matches are buried among hundreds of held lines.
   Where does each one land?
     baseline   Sift's original sheet order (class, tier, score)
     + vectors  qwen3-embedding-8b distance in pgvector
     + reader   qwen3-8-27b reads the closest 36 (same / maybe / different)
2. Distributor notice accuracy, the same checker applied to both designs:
     baseline   the model writes every item row
     new        the database writes the item table; the model writes wording only

    .venv/Scripts/python -m scripts.benchmark      (needs a finished run 1)
Writes data/benchmark.json.
"""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)
from pullsheet import db, location  # noqa: E402
from pullsheet.akamai import data, notice, semantic  # noqa: E402
from pullsheet.matching.run import ordered_matches  # noqa: E402
from scripts import _notice_v1 as notice_v1  # noqa: E402

TRIALS = 2


def ranking(conn, run_id: int) -> dict:
    truth = json.load(open(db.ROOT / "data/fixtures/expected_matches.json"))
    seeded = {(m["item_description"], m["recall_source_record_id"]) for m in truth["matches"]}
    sheet = [r for r in ordered_matches(conn, run_id) if r["status"] == "HELD"]
    base_rank = {r["id"]: i + 1 for i, r in enumerate(sheet)}
    held = data.held_lines(conn, run_id)
    true_ids = {h["match_id"] for h in held
                if (h["item"]["raw_description"], h["recall"]["source_record_id"]) in seeded}
    all_seeded_on_sheet = {(r["raw_description"], r["source_record_id"]) for r in ordered_matches(conn, run_id)} & seeded
    t = time.time()
    res = semantic.triage_held(held, data.active_recalls(conn), base_rank=base_rank)
    secs = round(time.time() - t, 1)
    ai_order = [h["match_id"] for h in res["read"]] + [h["match_id"] for h in res["rest"]]
    ai_rank = {m: i + 1 for i, m in enumerate(ai_order)}
    vec_order = sorted(res["read"] + res["rest"], key=lambda h: (h["distance"] is None, h["distance"] or 9))
    vec_rank = {h["match_id"]: i + 1 for i, h in enumerate(vec_order)}
    fused = semantic.fuse(res["read"] + res["rest"], base_rank)
    fused_rank = {h["match_id"]: i + 1 for i, h in enumerate(fused)}
    verdict = {h["match_id"]: h.get("verdict") for h in res["read"]}

    def stats(rank):
        rs = sorted(rank[m] for m in true_ids)
        return {"ranks": rs, "median": statistics.median(rs) if rs else None,
                "mean": round(statistics.mean(rs), 1) if rs else None,
                "in_top_10": sum(r <= 10 for r in rs), "in_top_36": sum(r <= 36 for r in rs),
                "first": rs[0] if rs else None}

    lines = []
    for h in held:
        if h["match_id"] in true_ids:
            lines.append({"item": h["item"]["raw_description"], "recall": h["recall"]["source_record_id"],
                          "baseline": base_rank[h["match_id"]], "vectors": vec_rank[h["match_id"]],
                          "fused": fused_rank[h["match_id"]],
                          "reader": ai_rank[h["match_id"]], "verdict": verdict.get(h["match_id"])})
    lines.sort(key=lambda x: x["reader"])
    return {"held_total": len(held), "seeded_total": len(seeded), "seeded_on_sheet": len(all_seeded_on_sheet),
            "true_held": len(true_ids), "seconds": secs,
            "baseline": stats(base_rank), "vectors": stats(vec_rank), "fused": stats(fused_rank),
            "reader": stats(ai_rank),
            "lines": lines}


def score_notice(draft: str, group: list[dict]) -> dict:
    """The original checker, applied to either design."""
    v = notice_v1.verify(draft, group, {"24", "24-hour", "48", "USDA"})
    wrong = sum(1 for c in v["checks"] if not c["ok"] and c["line"] not in v["missing"])
    return {"rows": len(group), "wrong_rows": wrong, "missing_rows": len(v["missing"]),
            "invented_figures": len(v["unverified"]), "all_ok": v["all_ok"]}


def notices(conn, run_id: int) -> dict:
    lines = data.pull_lines(conn, run_id)
    groups = list(notice.by_vendor(lines).items())
    jobs = [(design, vendor, group, trial) for trial in range(TRIALS)
            for vendor, group in groups for design in ("baseline", "new")]

    def run(job):
        design, vendor, group, trial = job
        t = time.time()
        if design == "baseline":
            draft = notice_v1.draft_for_vendor(vendor, group, location.NAME)
            wording_flags = None
        else:
            r = notice.draft_for_vendor(vendor, group, location.NAME, {"24", "24-hour", "USDA"})
            draft, wording_flags = r["draft"], len(r["unverified"])
        out = {"design": design, "vendor": vendor, "trial": trial + 1,
               "seconds": round(time.time() - t, 1), **score_notice(draft, group)}
        if wording_flags is not None:
            out["wording_flags"] = wording_flags
        return out

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, jobs))
    summary = {}
    for design in ("baseline", "new"):
        rs = [r for r in results if r["design"] == design]
        rows = sum(r["rows"] for r in rs)
        bad = sum(r["wrong_rows"] + r["missing_rows"] for r in rs)
        summary[design] = {"drafts": len(rs), "rows": rows, "bad_rows": bad,
                           "row_accuracy": round(100 * (rows - bad) / rows, 1) if rows else None,
                           "invented_figures": sum(r["invented_figures"] for r in rs),
                           "clean_drafts": sum(r["all_ok"] for r in rs),
                           "median_seconds": statistics.median(r["seconds"] for r in rs)}
    return {"summary": summary, "drafts": results}


def main():
    conn = db.connect()
    run = conn.execute("SELECT id FROM runs WHERE status='ok' ORDER BY id LIMIT 1").fetchone()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run["id"],
           "ranking": ranking(conn, run["id"])}
    print(json.dumps({k: v for k, v in out["ranking"].items() if k != "lines"}, indent=1))
    out["notice"] = notices(conn, run["id"])
    print(json.dumps(out["notice"]["summary"], indent=1))
    conn.close()
    (db.ROOT / "data/benchmark.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
