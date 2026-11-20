"""Read the rows the AI features need, through the app's own connection.

Plain SQL with `?` placeholders and rows read by column name, so it runs on the
SQLite database and on managed PostgreSQL through pullsheet.db alike.
"""

from __future__ import annotations

INVENTORY_COLS = ("id", "storage_location", "raw_description", "quantity", "unit", "pack_size",
                  "gtin", "lot_code", "brand", "manufacturer", "manufacturer_item_code",
                  "vendor_name", "vendor_item_code", "unit_cost")
RECALL_COLS = ("id", "source", "source_record_id", "recalling_firm", "product_description",
               "classification", "status", "reason_for_recall", "code_info")


def active_inventory(conn) -> list[dict]:
    rows = conn.execute(
        f"SELECT {', '.join(INVENTORY_COLS)} FROM inventory_records "
        "WHERE superseded_by IS NULL ORDER BY id").fetchall()
    return [{c: r[c] for c in INVENTORY_COLS} for r in rows]


def active_recalls(conn) -> list[dict]:
    """Every recall the matcher runs against: the same set corpus.active_records returns."""
    from pullsheet.recalls.corpus import active_records

    return [{c: r[c] for c in RECALL_COLS} for r in active_records(conn)]


def matched_pairs(conn, run_id: int) -> set[tuple[int, int]]:
    rows = conn.execute(
        "SELECT inventory_record_id, recall_record_id FROM matches WHERE run_id = ?",
        (run_id,)).fetchall()
    return {(r["inventory_record_id"], r["recall_record_id"]) for r in rows}


def pull_lines(conn, run_id: int) -> list[dict]:
    """One dict per PULL match in this run, both sides joined. Numbers come from here."""
    rows = conn.execute(
        """SELECT m.id AS match_id, i.raw_description, i.quantity, i.unit, i.pack_size,
                  i.vendor_name, i.vendor_item_code, i.lot_code, i.storage_location,
                  r.source, r.source_record_id, r.recalling_firm, r.classification
           FROM matches m
           JOIN inventory_records i ON i.id = m.inventory_record_id
           JOIN recall_records r ON r.id = m.recall_record_id
           WHERE m.run_id = ? AND m.status = 'PULL'
           ORDER BY r.class_rank, i.vendor_name, i.raw_description, m.id""",
        (run_id,)).fetchall()
    keys = ("match_id", "raw_description", "quantity", "unit", "pack_size", "vendor_name",
            "vendor_item_code", "lot_code", "storage_location", "source", "source_record_id",
            "recalling_firm", "classification")
    return [{k: r[k] for k in keys} for r in rows]


def held_lines(conn, run_id: int) -> list[dict]:
    """Every HELD match in this run, both sides, for the AI reading order."""
    rows = conn.execute(
        f"""SELECT m.id AS match_id, m.tier, m.evidence_kind,
                  {', '.join('i.' + c + ' AS i_' + c for c in INVENTORY_COLS)},
                  {', '.join('r.' + c + ' AS r_' + c for c in RECALL_COLS)}
           FROM matches m
           JOIN inventory_records i ON i.id = m.inventory_record_id
           JOIN recall_records r ON r.id = m.recall_record_id
           WHERE m.run_id = ? AND m.status = 'HELD'
           ORDER BY m.id""", (run_id,)).fetchall()
    return [{"match_id": r["match_id"], "tier": r["tier"], "evidence_kind": r["evidence_kind"],
             "item": {c: r["i_" + c] for c in INVENTORY_COLS},
             "recall": {c: r["r_" + c] for c in RECALL_COLS}} for r in rows]
