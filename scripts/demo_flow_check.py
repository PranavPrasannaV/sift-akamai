"""The demo flow end to end on Akamai: reset, day-1 export, day-2 export with one
new line, AI second look, distributor notice, label photo."""
import re, time
from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi.testclient import TestClient  # noqa: E402
from pullsheet.app import app  # noqa: E402
from pullsheet import db  # noqa: E402
import scripts.akamai_reset  # noqa: E402,F401  (resets on import)
c = TestClient(app, raise_server_exceptions=False)
def up(path, name):
    with open(path, "rb") as f:
        r = c.post("/ingest/upload", files={"file": (name, f.read(), "text/csv")}, follow_redirects=False)
    print("upload", name, r.status_code, r.headers.get("location"))
up(db.FIXTURES / "inventory_lincoln.csv", "inventory_lincoln.csv")
up(db.ROOT / "data/demo/inventory_lincoln_day2.csv", "inventory_lincoln_day2.csv")
conn = db.connect()
print([dict(x) for x in conn.execute("SELECT id, status, pull_count, held_count FROM runs ORDER BY id")])
print("chickpea matches:", conn.execute("""SELECT m.status, m.tier, r.source_record_id FROM matches m JOIN inventory_records i ON i.id=m.inventory_record_id
  JOIN recall_records r ON r.id=m.recall_record_id WHERE i.raw_description LIKE 'CHICKPEA%'""").fetchall())
t = time.time(); r = c.get("/ai/second-look"); txt = re.sub(r"<[^>]+>", " ", r.text)
print("second-look", r.status_code, f"{time.time()-t:.1f}s", "CHICKPEA" in r.text)
i = txt.find("CHICKPEA"); print(re.sub(r"\s+", " ", txt[max(0, i-200):i+500]))
with open(db.ROOT / "data/demo/case_label_hummus.png", "rb") as f:
    t = time.time(); r = c.post("/ai/label", files={"file": ("label.png", f.read(), "image/png")})
print("label", r.status_code, f"{time.time()-t:.1f}s", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[-900:])
