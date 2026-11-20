"""Render the three AI pages through FastAPI's TestClient against a throwaway
SQLite copy of the demo data, with the real Akamai services behind them.

    python scripts/ai_routes_check.py
"""

from __future__ import annotations

import io
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def label_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 420), "white")
    d = ImageDraw.Draw(img)
    try:
        big, small = ImageFont.truetype("arialbd.ttf", 44), ImageFont.truetype("arial.ttf", 30)
    except OSError:
        big = small = ImageFont.load_default()
    d.rectangle([10, 10, 890, 410], outline="black", width=4)
    d.text((40, 40), "SABRA CLASSIC HUMMUS", font=big, fill="black")
    d.text((40, 110), "17 OZ  -  SIX PACK", font=small, fill="black")
    d.text((40, 170), "Sabra Dipping Co., LLC", font=small, fill="black")
    d.text((40, 250), "UPC 0 40822 01749 7", font=small, fill="black")
    d.text((40, 310), "LOT 15-0412-B", font=small, fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    from fastapi.testclient import TestClient

    from scripts.ai_smoke import demo_sqlite
    conn = demo_sqlite()
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.close()

    from pullsheet import db

    def connect(*_a, **_k):
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    db.connect = connect
    from pullsheet.akamai.routes import router
    from pullsheet.app import app
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/ai/second-look")
    t = text_of(r.text)
    print("second-look", r.status_code, re.search(r"\d+ close in meaning.*?different product", t).group(0)
          if "close in meaning" in t else t[:400])

    r = client.get("/ai/notice")
    print("notice GET", r.status_code, "Draft the notices" in r.text)
    r = client.post("/ai/notice")
    t = text_of(r.text)
    print("notice POST", r.status_code, "traced:", t.count("every number traced"),
          "check-before-sending:", t.count("check before sending"), "failed checks:", r.text.count("✗"))
    for bad in re.findall(r'<li class="bad">(.*?)</li>', r.text, re.S):
        print("  FAILED:", text_of(bad).strip()[:200])
    for m in re.findall(r"Figures in the draft that are not in the data:(.*?)check or delete", t):
        print("  unverified:", m.strip())

    r = client.post("/ai/label", files={"file": ("label.png", label_png(), "image/png")})
    t = text_of(r.text)
    i = t.find("What the model read")
    print("label", r.status_code, t[i:i + 700] if i >= 0 else t[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
