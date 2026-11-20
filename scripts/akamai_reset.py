"""Reset the demo on Akamai Cloud: Sift's tables in PostgreSQL recreated, the
recall corpus and menu loaded, no runs, and the archived exports of the
previous rehearsal removed from Object Storage (run ids restart at 1).
The AI embedding cache is kept, so the second look does not re-embed.

    .venv/bin/python -m scripts.akamai_reset
"""
from dotenv import load_dotenv

load_dotenv(override=True)
from pullsheet import db, storage  # noqa: E402
from pullsheet.recalls.corpus import load_snapshots  # noqa: E402

db.reset()
conn = db.connect()
db.load_menu_fixtures(conn)
print("recall records:", load_snapshots(conn))
conn.close()
if storage.enabled():
    s3, bucket = storage._client(), storage._bucket()
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix="exports/").get("Contents", [])]
    for key in keys:
        s3.delete_object(Bucket=bucket, Key=key)
    print("removed", len(keys), "archived exports from the previous rehearsal")
print("ready: no runs. Upload data/fixtures/inventory_lincoln.csv on /ingest to start.")
