# Sift on Akamai Cloud

A food recall lands. Somewhere in the walk-in there are cases of the recalled
product, and a school kitchen has 24 hours to notify its distributor and 48 to
finish the inventory check. Today that means someone reading recall notices
against a spreadsheet by hand.

Sift turns the kitchen's inventory export into a printed **pull sheet**: what
to pull, where it is, and why. It matches 1,012 FDA and FSIS recall records
against every line. This repository runs Sift on **Akamai Cloud**:

- a Linode serves the app;
- managed PostgreSQL holds the data and the vectors;
- Object Storage keeps every file a run read;
- Akamai Inference (three models) does the work no rule can: it reads labels,
  orders what to look at first, and drafts the distributor email.

**Live:** `http://172.234.240.147` (Linode `sea-dev-web`, Seattle). `/health` shows each service connected. The Cloud Firewall currently admits only our own address, so the video is the public demo.

**The rule the whole thing is built around:** under-pulling risks a child, and
over-pulling only wastes a case of tomatoes.

- A match is `PULL` or `HELD`, enforced by a `CHECK` constraint. An
  automatically cleared line cannot be stored.
- The AI features keep that rule. They read, reorder and draft. None of them can
  clear a line, and every page they produce is labelled as AI output for a
  person to decide on.

---

## For the judges

```text
User and task: The kitchen manager of one school kitchen (or restaurant). When a
  recall lands, they must find every affected case, pull it, and notify their
  distributor within 24 hours.

Benefit: The inventory export the kitchen already produces becomes a pull sheet
  in seconds: 42 lines to pull, grouped by cooler, Class I first. Then:
  - the 814 held lines arrive in the order to read them;
  - a photo of a case label is checked against the recall corpus;
  - the distributor notice is drafted with every number traced back to the data.

Services:
  - Linode (Nanode, Seattle) runs the FastAPI app under systemd on port 80, with
    the folder watcher in the same process. Cloud Firewall sea-dev-fw allows only
    ports 22 and 80, and only from our address.
  - Managed PostgreSQL 19 (Seattle) is the system of record: all 10 Sift tables
    (runs, matches, decisions, recall corpus, menu), the same CHECK constraints,
    and nothing ever deleted. The same database stores pgvector embeddings of
    every recall and inventory description, and caches the model's verdicts. A
    rebuilt server loses nothing, and a re-run never re-embeds text it has
    already seen.
  - Object Storage (bucket sea-dev-files) keeps the original of every export a
    run read, accepted or refused, at exports/run-<id>/<file>. Each run's page
    links to its original with a presigned link that expires in an hour. The
    bucket stays private, and its access key can reach only this bucket.

Inference (Akamai endpoint, OpenAI-compatible):
  - qwen3-embedding-8b embeds 1,012 recall descriptions and every inventory line
    (4,096 dimensions, into pgvector). Cosine distance orders the held lines by
    how close their meanings are.
  - qwen3-8-27b reads the closest 36 held pairs and answers same, maybe or
    different, quoting the words that decide it.
  - qwen3-8-27b also writes one email per distributor from the pull lines.
  - gemma-4-26b-a4b-it reads a photo of a case label: product, firm, barcode,
    lot.
  Why these models: the embedding model ranks 827 pairs in one SQL query for
    almost nothing. The chat model then reads only the closest few. Gemma is the
    vision model on the endpoint.
  How we checked:
  - The demo export has 827 held lines. The model read the closest 36 and put
    two first:
    - Northfield sliced turkey breast against FSIS-RC-012-2026 (Class I),
      read as "same";
    - an unbranded chickpea dip against the Sabra Classic Hummus recall
      F-2085-2015, read as "maybe", with the reason that the brand is missing
      on the inventory side.
    It read 34 as different, each with a quoted reason, such as "SMOOTH" against
    "CRUNCHY" for peanut butter.
  - The label photo: Gemma read "0 40822 01749 7". An exact barcode lookup found
    recall F-2085-2015, Class I, and the meaning check agreed ("same", distance
    0.066).
  - The distributor email: a checker compares every number and code in the
    draft with the pull lines. When we changed one quantity by hand, it caught
    it. On the live server one draft came back "every number traced" and the
    other "check before sending". The page shows which.
  - An input the model cannot answer: when nothing close in meaning is left, the
    second-look page says so and adds nothing.

Technical choice: Sift's 4,700 lines of hand-written SQL moved to PostgreSQL
  without being rewritten.
  - pullsheet/pg.py gives psycopg the sqlite3 interface the code uses:
    placeholders, rows by name, lastrowid, executemany. It translates the three
    SQLite-only expressions.
  - schema_pg.sql keeps every CHECK constraint, and adds a SUM(boolean)
    aggregate so the count queries stay as written.
  - The same code still runs on SQLite when PGHOST is unset, which is how the
    test suite runs.
  - Parity check: on PostgreSQL the demo export gives exactly the original's
    numbers: 56 rows merged into 54 records, 856 lines, 42 PULL and 814 HELD.
  - Reliability: the pull sheet never waits on AI. If inference or storage is
    down, those pages say why and the sheet is unaffected.

Our idea: Recall tools either alert you or clear things for you. Sift does
  neither. It holds anything it cannot prove, and attaches the evidence to every
  line. The AI here is pointed at the cost of that safety, which is a long held
  list. It decides the reading order of the list, not its contents.

Demo: Upload data/fixtures/inventory_lincoln.csv on "Add inventory" and the pull
  sheet appears. Then:
  - Open "Run history", then the run, to see the original file in Object Storage.
  - Upload data/demo/inventory_lincoln_day2.csv, which is the same export plus
    one unbranded chickpea dip.
  - Open "Held: read first" to see the turkey breast and the chickpea dip at the
    top, out of 827 held lines.
  - Open "Check a label" and upload data/demo/case_label_hummus.png: the barcode
    matches the Class I Sabra recall.
  - Open "Distributor notice" and draft it: the drafts come back with the
    numbers checked.

Known limits:
  - The AI pages call the model on first view. "Held: read first" took about
    67 s cold and under 1 s cached. Drafting the notice takes about 60 s. There
    is no background queue yet.
  - A long notice draft is sometimes flagged "check before sending". A person
    still sends the email.
  - The FSIS corpus is hand-authored, because FSIS returns 403 to scripts. It is
    labelled that way on every screen.
  - There are no user accounts. The person recording a decision types their
    name.
  - The original Sift could run with no network. This deployment needs its
    database. SQLite mode still exists for an offline kitchen.
  - The Next.js dashboard in web/ was not deployed. The server-rendered app is
    the one live.
```

### Where each service is in the code

| Service | File | What it does |
|---|---|---|
| Managed PostgreSQL | `pullsheet/pg.py`, `pullsheet/schema_pg.sql`, `pullsheet/db.py` (`connect`, `reset`) | System of record for all Sift tables |
| PostgreSQL + pgvector | `pullsheet/akamai/semantic.py` | Recall and inventory embeddings, cached model verdicts |
| Object Storage | `pullsheet/storage.py`, called from `db.ingest_file` | Original of every export, presigned links on `/runs/{id}` |
| Inference: embeddings and chat | `pullsheet/akamai/semantic.py`, `pullsheet/akamai/inference.py` | `/ai/triage`, `/ai/second-look` |
| Inference: chat | `pullsheet/akamai/notice.py` | `/ai/notice`: drafts, then checks every number |
| Inference: vision | `pullsheet/akamai/vision.py` | `/ai/label`: reads a case label photo |
| Linode | `deploy/sift.service`, `deploy/deploy.sh` | systemd service on port 80 |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in the Akamai values
.venv/bin/python -m scripts.akamai_reset     # tables, recall corpus, menu; no runs
.venv/bin/python -m pullsheet.main --port 8000
```

Leave out the `PG` lines in `.env` and Sift uses a local SQLite file. Leave out
`OBJ_BUCKET` and it does not archive.

To deploy to a Linode with `uv` installed, run `IP=<linode-ip> bash deploy/deploy.sh`.

Checks against the real services:

- `scripts/pg_smoke.py`: every page on PostgreSQL.
- `scripts/pg_actions.py`: decisions and a second upload.
- `scripts/demo_flow_check.py`: the whole demo.
- `scripts/triage_check.py`
- `scripts/ai_smoke.py`

Tests: run `.venv/bin/python -m pytest -q` (SQLite). On Windows,
`tests/integration/test_network_off.py` fails because it blocks sockets that
the Windows asyncio loop needs.

## Where this came from

This is a port of [Sift](https://github.com/PranavPrasannaV/Sift), our earlier
SQLite-only, offline project, to Akamai Cloud for the Seattle Build with Akamai
Cloud buildathon. The matching engine, rules, fixtures and server-rendered pages
are Sift's. New for this event:

- the PostgreSQL port;
- Object Storage archiving;
- all of `pullsheet/akamai/`: embeddings with pgvector, the held-line reading
  order, the second look, the distributor notice and the label reader;
- the Linode deployment.

Sift's full design notes, demo script and hostile-question table are in
[docs/sift-original-README.md](docs/sift-original-README.md).
