"""Exercise the Akamai inference features against the real services.

    python scripts/ai_smoke.py            # a throwaway SQLite copy of the demo data
    python scripts/ai_smoke.py --app-db   # the app's own database (db.connect())

Prints the AI second-look suggestions, the distance spread used to pick the
threshold, and one drafted distributor notice with its checks, including a
deliberately corrupted copy that the checker must catch.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

from pullsheet import location  # noqa: E402
from pullsheet.akamai import data, notice, semantic  # noqa: E402


def demo_sqlite() -> sqlite3.Connection:
    """The committed corpus plus inventory_lincoln.csv, matched, in a temp file."""
    from pullsheet import db
    from pullsheet.adapters.sftp_drop import SftpDropAdapter
    from pullsheet.recalls.corpus import load_snapshots

    path = Path(tempfile.mkdtemp()) / "smoke.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "pullsheet" / "schema.sql").read_text())
    db.load_menu_fixtures(conn)
    load_snapshots(conn)
    result = db.ingest_file(conn, ROOT / "data" / "fixtures" / "inventory_lincoln.csv",
                            SftpDropAdapter())
    conn.commit()
    print(f"ingest: {result['status']}  run {result.get('run_id')}  matches {result.get('matches')}")
    return conn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-db", action="store_true")
    ap.add_argument("--skip-notice", action="store_true")
    args = ap.parse_args()

    if args.app_db:
        from pullsheet import db
        conn = db.connect()
    else:
        conn = demo_sqlite()
    from pullsheet import db
    run = db.latest_ok_run(conn)
    run_id = run["id"]
    inventory, recalls = data.active_inventory(conn), data.active_recalls(conn)
    pairs = data.matched_pairs(conn, run_id)
    print(f"run {run_id}: {len(inventory)} active inventory lines, {len(recalls)} recalls, "
          f"{len(pairs)} matcher pairs")

    print("\n== embeddings ==")
    print(semantic.ensure_recall_embeddings(recalls))

    dist = semantic.all_distances(inventory, recalls)
    nearest = {}
    for inv_id, rec_id, d in dist:
        nearest.setdefault(inv_id, []).append((d, rec_id))
    paired = [d for inv_id, rec_id, d in dist if (inv_id, rec_id) in pairs]
    unpaired_top1 = [min(v)[0] for k, v in nearest.items()]
    buckets = Counter(round(d, 1) for d in unpaired_top1)
    print("nearest-neighbour distance per item (rounded):", dict(sorted(buckets.items())))
    if paired:
        print(f"distances of top-5 neighbours the matcher ALSO paired: min {min(paired):.3f} "
              f"median {sorted(paired)[len(paired)//2]:.3f} max {max(paired):.3f} (n={len(paired)})")

    print("\n== second look (threshold", semantic.MAX_DISTANCE, ") ==")
    found = semantic.second_look(inventory, recalls, pairs)
    print(f"{len(found)} suggestions")
    for s in found[:15]:
        print(f"  {s['distance']:.3f}  {s['item']['raw_description'][:45]:45s} -> "
              f"{s['recall']['source_record_id']}  {s['recall']['product_description'][:60]}")

    print("\n== reviewed second look (retrieve <=", semantic.RETRIEVE_DISTANCE, ", chat model reads each) ==")
    rev = semantic.reviewed_second_look(inventory, recalls, pairs)
    print(f"retrieved {rev['retrieved']}  judged now {rev['judged_now']}  "
          f"shown {len(rev['suggestions'])}  dismissed as different {rev['dismissed']}")
    for s in rev["suggestions"][:20]:
        print(f"  {s['verdict']:5s} {s['distance']:.3f}  {s['item']['raw_description'][:40]:40s} -> "
              f"{s['recall']['source_record_id']}  {s['recall']['product_description'][:50]}  | {s['reason']}")

    if args.skip_notice:
        return 0
    print("\n== distributor notice ==")
    lines = data.pull_lines(conn, run_id)
    groups = notice.by_vendor(lines)
    print({v: len(g) for v, g in groups.items()})
    vendor, group = min(groups.items(), key=lambda kv: len(kv[1]))
    group = group[:6]
    result = notice.draft_for_vendor(vendor, group, location.NAME, {"24", "24-hour", "USDA"})
    print(result["draft"])
    table_ok = notice.item_table(group) in result["draft"]
    print(f"item table built from the database: {table_ok}  model wording added: {result['unverified']}")

    # A model that slips data or an instruction into its own words is caught.
    q = notice._fmt_qty(group[0]["quantity"])
    bad = notice.verify_prose(f"Please destroy the {int(float(q)) + 7} cases of item "
                              f"{group[0]['vendor_item_code']}.", group, {"24"})
    print(f"planted number, code and 'destroy' in the wording: caught {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
