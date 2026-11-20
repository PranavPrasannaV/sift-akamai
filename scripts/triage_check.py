import re, time
from dotenv import load_dotenv
load_dotenv(override=True)
from fastapi.testclient import TestClient  # noqa: E402
from pullsheet.app import app  # noqa: E402
c = TestClient(app, raise_server_exceptions=False)
t = time.time(); r = c.get("/ai/triage"); print(r.status_code, f"{time.time()-t:.1f}s")
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
i = txt.find("Run #"); print(txt[i:i+2500])
