"""Exercise the write paths on PostgreSQL: a human decision and a second upload."""
from dotenv import load_dotenv

load_dotenv(override=True)
from fastapi.testclient import TestClient  # noqa: E402
from pullsheet import db  # noqa: E402
from pullsheet.app import app  # noqa: E402

c = TestClient(app, raise_server_exceptions=False)
conn = db.connect()
held = conn.execute("SELECT id FROM matches WHERE status='HELD' ORDER BY id LIMIT 1").fetchone()["id"]
pull = conn.execute("SELECT id FROM matches WHERE status='PULL' ORDER BY id LIMIT 1").fetchone()["id"]
conn.close()
r = c.post(f"/match/{held}/clear", data={"actor": "smoke test", "note": "checked case label"}, follow_redirects=False)
print("clear", r.status_code, r.headers.get("location"))
r = c.post(f"/match/{pull}/confirm-pulled", data={"actor": "smoke test"}, follow_redirects=False)
print("confirm", r.status_code, r.headers.get("location"))
print("match page", c.get(f"/match/{held}").status_code)
with open(db.FIXTURES / "inventory_lincoln.csv", "rb") as f:
    data = f.read().replace(b"\n", b"\n", 1)
r = c.post("/ingest/upload", files={"file": ("inventory_day2.csv", data + b"\n", "text/csv")}, follow_redirects=False)
print("upload", r.status_code, r.headers.get("location"), r.text[:200] if r.status_code >= 400 else "")
print("runs", c.get("/runs").status_code, c.get("/sheet").status_code)
conn = db.connect()
print([dict(x) for x in conn.execute("SELECT id, channel, status, pull_count, held_count FROM runs ORDER BY id")])
print(conn.execute("SELECT kind, actor FROM decisions").fetchall())
