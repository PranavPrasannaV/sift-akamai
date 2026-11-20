"""AI second look: meaning-based neighbours the deterministic matcher did not pair.

The matcher in pullsheet/matching reads supplier identity and codes. It cannot
see that "BREADED CHICKEN TENDERS" and "chicken strips, breaded, fully cooked"
are the same product when no firm or code links them. This module embeds both
sides with EMBEDDING_MODEL (qwen3-embedding-8b, 4,096 numbers per text), keeps
the vectors in managed PostgreSQL with pgvector, and ranks recalls by cosine
distance for every active inventory line.

The output is a list of SUGGESTIONS for a person to look at. Sift's rule is that
every rule widens and nothing clears a line by itself, so this module can only
ever add attention. It never writes to `matches` and never produces PULL or HELD.

Vectors are cached by a hash of the exact text that was embedded, so a daily run
re-embeds only descriptions it has never seen.
"""

from __future__ import annotations

import hashlib
import os

from pullsheet.akamai import inference

DIMS = 4096
# Cosine distance at or under which a neighbour is worth a person's time.
# Chosen against the committed fixtures: see scripts/ai_smoke.py and the README.
MAX_DISTANCE = float(os.environ.get("SECOND_LOOK_MAX_DISTANCE", "0.30"))

SCHEMA = f"""
create extension if not exists vector;
create table if not exists ai_recall_embeddings (
  source           text not null,
  source_record_id text not null,
  text_hash        text not null,
  embedding        vector({DIMS}) not null,
  primary key (source, source_record_id)
);
create table if not exists ai_text_embeddings (
  text_hash text primary key,
  embedding vector({DIMS}) not null
);
"""


def _pg():
    import psycopg

    conn = psycopg.connect(connect_timeout=10)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def recall_text(r: dict) -> str:
    firm = (r.get("recalling_firm") or "").strip()
    desc = (r.get("product_description") or "").strip()
    return f"{desc} | {firm}" if firm else desc


def inventory_text(i: dict) -> str:
    who = " ".join(x for x in (i.get("brand"), i.get("manufacturer")) if x)
    desc = (i.get("raw_description") or "").strip()
    return f"{desc} | {who}" if who else desc


def ensure_recall_embeddings(recalls: list[dict], conn=None) -> dict[str, int]:
    """Embed every recall whose text changed or was never embedded. Safe to rerun."""
    own = conn is None
    conn = conn or _pg()
    try:
        have = {(s, sid): h for s, sid, h in conn.execute(
            "select source, source_record_id, text_hash from ai_recall_embeddings")}
        todo = []
        for r in recalls:
            text = recall_text(r)
            h = _hash(text)
            if have.get((r["source"], r["source_record_id"])) != h:
                todo.append((r, text, h))
        for i in range(0, len(todo), 64):
            chunk = todo[i:i + 64]
            vectors = inference.embed([t for _, t, _ in chunk])
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into ai_recall_embeddings (source, source_record_id, text_hash, embedding)
                       values (%s, %s, %s, %s::vector)
                       on conflict (source, source_record_id) do update
                       set text_hash = excluded.text_hash, embedding = excluded.embedding""",
                    [(r["source"], r["source_record_id"], h, _vec(v))
                     for (r, _, h), v in zip(chunk, vectors)])
            conn.commit()
        return {"recalls": len(recalls), "embedded_now": len(todo), "cached": len(recalls) - len(todo)}
    finally:
        if own:
            conn.close()


def _ensure_text_embeddings(conn, texts: list[str]) -> dict[str, str]:
    hashes = {t: _hash(t) for t in texts}
    have = {h for (h,) in conn.execute(
        "select text_hash from ai_text_embeddings where text_hash = any(%s)", (list(hashes.values()),))}
    todo = [t for t, h in hashes.items() if h not in have]
    if todo:
        vectors = inference.embed(todo)
        with conn.cursor() as cur:
            cur.executemany(
                "insert into ai_text_embeddings (text_hash, embedding) values (%s, %s::vector) "
                "on conflict (text_hash) do nothing",
                [(hashes[t], _vec(v)) for t, v in zip(todo, vectors)])
        conn.commit()
    return hashes


def _neighbours(conn, text_hash: str, limit: int):
    return conn.execute(
        """select r.source, r.source_record_id, r.embedding <=> t.embedding as distance
           from ai_recall_embeddings r, ai_text_embeddings t
           where t.text_hash = %s
           order by distance limit %s""", (text_hash, limit)).fetchall()


def second_look(inventory: list[dict], recalls: list[dict], matched_pairs: set[tuple[int, int]],
                k: int = 3, max_distance: float | None = None, conn=None) -> list[dict]:
    """For each inventory line, up to k nearest recall records within max_distance
    that the matcher did not already pair with it. Sorted closest first.

    inventory: dicts with id, raw_description, brand, manufacturer (the whole dict
    is passed through as `item`). recalls: dicts with id, source, source_record_id,
    product_description, recalling_firm, classification.
    matched_pairs: {(inventory_id, recall_id)} the deterministic matcher produced.
    """
    limit = MAX_DISTANCE if max_distance is None else max_distance
    own = conn is None
    conn = conn or _pg()
    try:
        ensure_recall_embeddings(recalls, conn)
        by_key = {(r["source"], r["source_record_id"]): r for r in recalls}
        texts = {i["id"]: inventory_text(i) for i in inventory}
        hashes = _ensure_text_embeddings(conn, list(set(texts.values())))
        out = []
        for item in inventory:
            kept = 0
            for source, sid, distance in _neighbours(conn, hashes[texts[item["id"]]], k + 10):
                recall = by_key.get((source, sid))
                if recall is None or distance > limit:
                    continue
                if (item["id"], recall["id"]) in matched_pairs:
                    continue
                out.append({"item": item, "recall": recall, "distance": round(float(distance), 4),
                            "inventory_text": texts[item["id"]], "recall_text": recall_text(recall)})
                kept += 1
                if kept >= k:
                    break
        out.sort(key=lambda s: s["distance"])
        return out
    finally:
        if own:
            conn.close()


def all_distances(inventory: list[dict], recalls: list[dict], conn=None) -> list[tuple]:
    """(inventory_id, recall_id, distance) for each item's 5 nearest. Used to pick
    the threshold, not by the app."""
    own = conn is None
    conn = conn or _pg()
    try:
        ensure_recall_embeddings(recalls, conn)
        by_key = {(r["source"], r["source_record_id"]): r for r in recalls}
        texts = {i["id"]: inventory_text(i) for i in inventory}
        hashes = _ensure_text_embeddings(conn, list(set(texts.values())))
        out = []
        for item in inventory:
            for s, sid, d in _neighbours(conn, hashes[texts[item["id"]]], 5):
                if (s, sid) in by_key:
                    out.append((item["id"], by_key[(s, sid)]["id"], float(d)))
        return out
    finally:
        if own:
            conn.close()


def nearest(text: str, recalls: list[dict], k: int = 5, conn=None) -> list[dict]:
    """Nearest recalls to one free-text description (used by the label reader)."""
    own = conn is None
    conn = conn or _pg()
    try:
        ensure_recall_embeddings(recalls, conn)
        by_key = {(r["source"], r["source_record_id"]): r for r in recalls}
        h = _ensure_text_embeddings(conn, [text])[text]
        return [{"recall": by_key[(s, sid)], "distance": round(float(d), 4)}
                for s, sid, d in _neighbours(conn, h, k) if (s, sid) in by_key]
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Second opinion: the chat model reads each retrieved pair.
#
# Embedding distance finds "same aisle", not "same product": bread lands next
# to sourdough, turkey next to diced chicken. So retrieval is wide and a second
# model call reads both records and answers same / maybe / different with a
# reason. Only same and maybe are shown. Neither can clear anything: a pair the
# matcher already made is never sent here, so "different" only declines to ADD.

JUDGE_SCHEMA = """
create table if not exists ai_pair_judgements (
  inventory_hash   text not null,
  source           text not null,
  source_record_id text not null,
  verdict          text not null check (verdict in ('same', 'maybe', 'different')),
  reason           text not null,
  model            text not null,
  judged_at        timestamptz not null default now(),
  primary key (inventory_hash, source, source_record_id)
);
"""

JUDGE_SYSTEM = (
    "You check food recall notices against a school kitchen's inventory. Reply with JSON only."
)
JUDGE_PROMPT = """/no_think
For each numbered pair, decide whether the inventory line could be the recalled product.
- "same": the same specific product, and nothing on either side contradicts the maker or brand.
- "maybe": the same specific product, but the maker cannot be checked from what is given.
- "different": a different product (a similar category is NOT enough), or the brand/maker contradicts.
Reason in at most 15 words, quoting the words that decide it.
Return a JSON array: [{{"pair": <number>, "verdict": "same|maybe|different", "reason": "..."}}]

{pairs}
"""
RETRIEVE_DISTANCE = float(os.environ.get("SECOND_LOOK_RETRIEVE_DISTANCE", "0.22"))


def _judge_batch(batch: list[dict]) -> list[dict]:
    import json

    text = "\n".join(
        f"{n}. INVENTORY: {c['inventory_text']}\n   RECALL {c['recall']['source_record_id']}: "
        f"{c['recall_text'][:300]}" for n, c in enumerate(batch, 1))
    raw = inference.chat(JUDGE_SYSTEM, JUDGE_PROMPT.format(pairs=text), max_tokens=80 * len(batch) + 200,
                         temperature=0)
    start, end = raw.find("["), raw.rfind("]")
    try:
        parsed = json.loads(raw[start:end + 1]) if start >= 0 else []
    except ValueError:
        parsed = []
    by_pair = {p.get("pair"): p for p in parsed if isinstance(p, dict)}
    out = []
    for n, c in enumerate(batch, 1):
        p = by_pair.get(n, {})
        verdict = p.get("verdict") if p.get("verdict") in ("same", "maybe", "different") else "maybe"
        reason = (p.get("reason") or "the model gave no readable answer; shown so a person checks").strip()
        out.append({**c, "verdict": verdict, "reason": reason[:200]})
    return out


def reviewed_second_look(inventory: list[dict], recalls: list[dict],
                         matched_pairs: set[tuple[int, int]], k: int = 3,
                         max_distance: float | None = None, batch_size: int = 12,
                         conn=None) -> dict:
    """Retrieve unpaired neighbours, have CHAT_MODEL read each, cache the verdicts.

    Returns {"suggestions": same+maybe, closest first, "dismissed": n,
    "retrieved": n, "judged_now": n}.
    """
    model = os.environ.get("CHAT_MODEL", "qwen3-8-27b")
    own = conn is None
    conn = conn or _pg()
    try:
        conn.execute(JUDGE_SCHEMA)
        conn.commit()
        cands = second_look(inventory, recalls, matched_pairs, k=k,
                            max_distance=RETRIEVE_DISTANCE if max_distance is None else max_distance,
                            conn=conn)
        for c in cands:
            c["inventory_hash"] = _hash(c["inventory_text"])
        cached = {(h, s, sid): (v, r) for h, s, sid, v, r in conn.execute(
            "select inventory_hash, source, source_record_id, verdict, reason from ai_pair_judgements")}
        todo, done = [], []
        for c in cands:
            key = (c["inventory_hash"], c["recall"]["source"], c["recall"]["source_record_id"])
            if key in cached:
                done.append({**c, "verdict": cached[key][0], "reason": cached[key][1]})
            else:
                todo.append(c)
        for i in range(0, len(todo), batch_size):
            judged = _judge_batch(todo[i:i + batch_size])
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into ai_pair_judgements
                       (inventory_hash, source, source_record_id, verdict, reason, model)
                       values (%s, %s, %s, %s, %s, %s) on conflict do nothing""",
                    [(c["inventory_hash"], c["recall"]["source"], c["recall"]["source_record_id"],
                      c["verdict"], c["reason"], model) for c in judged])
            conn.commit()
            done.extend(judged)
        shown = sorted((c for c in done if c["verdict"] != "different"),
                       key=lambda c: (c["verdict"] != "same", c["distance"]))
        return {"suggestions": shown, "dismissed": len(done) - len(shown),
                "retrieved": len(done), "judged_now": len(todo)}
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Reading order for HELD lines.
#
# The matcher widens on purpose, so most lines on a sheet are HELD (814 of 856
# on the demo data). A person has to read them all; the question is which first.
# Every HELD pair gets a meaning distance from the stored vectors (one SQL query),
# and the closest READ_TOP are read by the chat model. The page reorders; it
# never clears, and a "different" reading leaves the line HELD.

READ_TOP = int(os.environ.get("TRIAGE_READ_TOP", "36"))


RRF_K = 60  # reciprocal rank fusion constant (Cormack et al., 2009)


def fuse(held: list[dict], base_rank: dict[int, int] | None) -> list[dict]:
    """Order held pairs by reciprocal rank fusion of two independent signals:
    Sift's own rule-based sheet order (codes, firm, words) and meaning distance.
    Each catches matches the other buries; fusion keeps both near the top."""
    by_vec = sorted(held, key=lambda h: (h["distance"] is None, h["distance"] or 9))
    vec_rank = {h["match_id"]: i + 1 for i, h in enumerate(by_vec)}
    if not base_rank:
        return by_vec
    worst = len(held) + 1

    def score(h):
        return 1 / (RRF_K + base_rank.get(h["match_id"], worst)) + 1 / (RRF_K + vec_rank[h["match_id"]])

    return sorted(held, key=lambda h: (-score(h), h["match_id"]))


def triage_held(held: list[dict], recalls: list[dict], read_top: int = READ_TOP,
                batch_size: int = 12, conn=None, base_rank: dict[int, int] | None = None) -> dict:
    model = os.environ.get("CHAT_MODEL", "qwen3-8-27b")
    own = conn is None
    conn = conn or _pg()
    try:
        conn.execute(JUDGE_SCHEMA)
        conn.commit()
        ensure_recall_embeddings(recalls, conn=conn)
        for h in held:
            h["inventory_text"] = inventory_text(h["item"])
            h["recall_text"] = recall_text(h["recall"])
        hashes = _ensure_text_embeddings(conn, sorted({h["inventory_text"] for h in held}))
        for h in held:
            h["inventory_hash"] = hashes[h["inventory_text"]]
        rows = conn.execute(
            """select p.ih, p.src, p.sid, r.embedding <=> t.embedding
                 from unnest(%s::text[], %s::text[], %s::text[]) as p(ih, src, sid)
                 join ai_text_embeddings t on t.text_hash = p.ih
                 join ai_recall_embeddings r on r.source = p.src and r.source_record_id = p.sid""",
            ([h["inventory_hash"] for h in held], [h["recall"]["source"] for h in held],
             [h["recall"]["source_record_id"] for h in held])).fetchall()
        dist = {(ih, s, sid): float(d) for ih, s, sid, d in rows}
        for h in held:
            h["distance"] = dist.get((h["inventory_hash"], h["recall"]["source"],
                                      h["recall"]["source_record_id"]))
        ordered = fuse(held, base_rank)
        fused_pos = {h["match_id"]: i for i, h in enumerate(ordered)}
        top = ordered[:read_top]
        cached = {(ih, s, sid): (v, r) for ih, s, sid, v, r in conn.execute(
            "select inventory_hash, source, source_record_id, verdict, reason from ai_pair_judgements")}
        todo = []
        for h in top:
            key = (h["inventory_hash"], h["recall"]["source"], h["recall"]["source_record_id"])
            if key in cached:
                h["verdict"], h["reason"] = cached[key]
            else:
                todo.append(h)
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            judged = _judge_batch(batch)
            for h, j in zip(batch, judged):
                h["verdict"], h["reason"] = j["verdict"], j["reason"]
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into ai_pair_judgements
                       (inventory_hash, source, source_record_id, verdict, reason, model)
                       values (%s, %s, %s, %s, %s, %s) on conflict do nothing""",
                    [(h["inventory_hash"], h["recall"]["source"], h["recall"]["source_record_id"],
                      h["verdict"], h["reason"], model) for h in batch])
            conn.commit()
        rank = {"same": 0, "maybe": 1, "different": 2}
        top.sort(key=lambda h: (rank.get(h.get("verdict"), 1), fused_pos[h["match_id"]]))
        counts = {v: sum(1 for h in top if h.get("verdict") == v) for v in rank}
        return {"read": top, "rest": ordered[read_top:], "held_total": len(held),
                "counts": counts, "judged_now": len(todo)}
    finally:
        if own:
            conn.close()
