import time
from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi.testclient import TestClient  # noqa: E402
from pullsheet.app import app  # noqa: E402
c = TestClient(app, raise_server_exceptions=False)
for path in ["/ai/second-look", "/ai/notice", "/ai/label"]:
    t = time.time(); r = c.get(path); print(r.status_code, path, len(r.text), f"{time.time()-t:.1f}s")
    if r.status_code >= 400: print(r.text[:500])
