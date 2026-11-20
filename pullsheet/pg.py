"""Akamai managed PostgreSQL behind the same small interface the code already uses.

Sift was written against ``sqlite3`` with hand-written SQL and no ORM. Rather
than rewrite ~60 call sites, this module gives a psycopg connection the handful
of sqlite3 behaviours that code relies on:

- ``?`` placeholders (translated to ``%s``)
- rows readable by index, by column name, and through ``dict(row)``
- ``cursor.lastrowid`` after an INSERT (via ``RETURNING id``)
- ``executemany`` and ``executescript``

and translates the three SQLite-only expressions the code contains
(``char(n)``, ``json_extract``, ``IS NOT ?``). ``SUM(boolean)`` is handled in
the schema by a small aggregate, so the queries stay as written.

The connection is chosen in ``pullsheet.db.connect``: PostgreSQL whenever
``PGHOST`` is set, SQLite otherwise (the test suite runs on SQLite).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import psycopg

SCHEMA = Path(__file__).resolve().parent / "schema_pg.sql"

# Every table Sift owns. reset() drops only these, never another table in the
# same database (the embedding cache lives alongside them).
TABLES = ("decisions", "matches", "inventory_records", "recall_records",
          "recall_snapshots", "service_days", "recipe_components",
          "recipe_ingredients", "recipes", "runs")

_CHAR = re.compile(r"\bchar\((\d+)\)", re.IGNORECASE)
_JSON_EXTRACT = re.compile(r"json_extract\(\s*(\w+)\s*,\s*'\$\.(\w+)'\s*\)", re.IGNORECASE)
_IS_NOT_PARAM = re.compile(r"\bIS NOT \?", re.IGNORECASE)
_INSERT = re.compile(r"^\s*INSERT\b", re.IGNORECASE)
_RETURNING = re.compile(r"\bRETURNING\b", re.IGNORECASE)


_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def translate(sql: str, has_params: bool, named: bool = False) -> str:
    sql = _CHAR.sub(r"chr(\1)", sql)
    # json_extract(col, '$.key') used as a truthy test in a CASE.
    sql = _JSON_EXTRACT.sub(
        r"(COALESCE(\1::jsonb->>'\2', 'false') NOT IN ('false', '0', '', 'null'))", sql)
    sql = _IS_NOT_PARAM.sub("IS DISTINCT FROM ?", sql)
    if named:
        # ":x IS NULL" gives PostgreSQL no type for the parameter; say it is text.
        sql = re.sub(r"(?<![:\w]):(\w+) IS NULL", r"CAST(:\1 AS text) IS NULL", sql)
        sql = _NAMED.sub(lambda m: "%(" + m.group(1) + ")s", sql.replace("%", "%%"))
    elif has_params:
        sql = sql.replace("%", "%%").replace("?", "%s")
    return sql


class Row(tuple):
    """A tuple that also answers row["name"] and dict(row), like sqlite3.Row."""

    _names: tuple[str, ...] = ()

    def __new__(cls, values, names):
        row = super().__new__(cls, values)
        row._names = names
        return row

    def keys(self):
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._names.index(key))
            except ValueError:
                lowered = key.lower()
                for i, name in enumerate(self._names):
                    if name.lower() == lowered:
                        return tuple.__getitem__(self, i)
                raise IndexError(f"No item with that key: {key}") from None
        return tuple.__getitem__(self, key)


def _row_factory(cursor):
    names = tuple(d.name for d in cursor.description) if cursor.description else ()
    return lambda values: Row(values, names)


def _params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return {k: int(v) if isinstance(v, bool) else v for k, v in params.items()}
    # SQLite stores a Python bool as 0/1; PostgreSQL refuses a bool for an
    # INTEGER column, so send what SQLite would have stored.
    return tuple(int(p) if isinstance(p, bool) else p for p in params)


class Cursor:
    def __init__(self, cur: psycopg.Cursor, lastrowid: int | None = None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """The subset of sqlite3.Connection that Sift calls."""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self.row_factory = None  # accepted and ignored; rows are always Row

    def execute(self, sql: str, params: Iterable | None = None) -> Cursor:
        params = _params(params) if params is not None else None
        if params == ():
            params = None
        returning = bool(_INSERT.match(sql)) and not _RETURNING.search(sql)
        text = translate(sql, params is not None, isinstance(params, dict))
        if returning:
            text = text.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.execute(text, params)
        lastrowid = None
        if returning:
            got = cur.fetchone()
            lastrowid = got[0] if got else None
        return Cursor(cur, lastrowid)

    def executemany(self, sql: str, seq: Iterable[Iterable]) -> Cursor:
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.executemany(translate(sql, True), [_params(p) for p in seq])
        return Cursor(cur)

    def executescript(self, script: str) -> None:
        self._conn.execute(script)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect() -> Connection:
    """psycopg reads PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, PGSSLMODE."""
    return Connection(psycopg.connect(connect_timeout=10))


def reset() -> None:
    """Drop Sift's own tables and recreate them from schema_pg.sql."""
    with psycopg.connect(connect_timeout=10) as conn:
        conn.execute("DROP TABLE IF EXISTS " + ", ".join(TABLES) + " CASCADE")
        conn.execute(SCHEMA.read_text())
