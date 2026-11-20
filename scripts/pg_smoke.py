"""Reset Sift's tables in Akamai PostgreSQL, load the corpus, ingest the fixture
export, and render every page. Prints timings and counts."""
import time
from dotenv import load_dotenv

load_dotenv(override=True)
from pullsheet import db  # noqa: E402
from pullsheet.recalls.corpus import load_snapshots  # noqa: E402

t = time.time()
db.reset()
conn = db.connect()
print("menu", db.load_menu_fixtures(conn))
print("corpus", load_snapshots(conn), f"{time.time()-t:.1f}s")
from pullsheet.adapters.sftp_drop import SftpDropAdapter  # noqa: E402
res = db.ingest_file(conn, db.FIXTURES / "inventory_lincoln.csv", SftpDropAdapter())
print("ingest", {k: res.get(k) for k in ("status", "run_id", "rows_read", "records_written", "archived_key")}, res.get("matches"), f"{time.time()-t:.1f}s")
conn.close()

from fastapi.testclient import TestClient  # noqa: E402
from pullsheet.app import app  # noqa: E402
c = TestClient(app, raise_server_exceptions=False)
mid = None
for path in ["/", "/sheet", "/runs", "/impact", "/artifacts/hold", "/artifacts/credit-claim",
             "/artifacts/state-report", "/sources", "/api/v1/sheet", "/api/v1/runs"]:
    r = c.get(path)
    print(r.status_code, path, len(r.text))
import re  # noqa: E402
m = re.search(r'href="/match/(\d+)"', c.get("/sheet").text)
if m:
    r = c.get(f"/match/{m.group(1)}"); print(r.status_code, f"/match/{m.group(1)}")
print(f"total {time.time()-t:.1f}s")
r = c.get("/runs/1"); print(r.status_code, "/runs/1", "linodeobjects" in r.text)
print(c.get("/health").json())
