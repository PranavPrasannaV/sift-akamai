"""Record the live demo: real Chrome driving the live Linode deployment.

Nothing is mocked. Every page is the deployed app answering from Akamai
PostgreSQL, Object Storage and Inference. A caption bar and a cursor are drawn
on top of the page so a viewer can follow along; scrolling is the browser's own.

    .venv/Scripts/python -m scripts.record_demo     (reset the demo first)

Writes demo/raw.webm and demo/cuts.json (where the model waits are, so the
encoder can cut them and say so on screen).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://172.234.240.147"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo"
W, H = 1440, 900

OVERLAY = r"""
(() => {
  if (window.__siftOverlay) return;
  window.__siftOverlay = true;
  const css = `
    #sift-cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(12px);
      max-width:1060px;width:calc(100% - 120px);padding:16px 26px;border-radius:14px;
      background:rgba(20,24,22,.86);color:#fff;font:500 21px/1.42 "Segoe UI",system-ui,sans-serif;
      letter-spacing:.005em;box-shadow:0 10px 40px rgba(0,0,0,.28);z-index:2147483647;
      opacity:0;transition:opacity .45s ease, transform .45s ease;pointer-events:none;text-align:left}
    #sift-cap.on{opacity:1;transform:translateX(-50%) translateY(0)}
    #sift-cap b{color:#9fe0b5;font-weight:650}
    #sift-cap .k{display:block;font-size:13px;letter-spacing:.12em;text-transform:uppercase;
      color:#9fe0b5;margin-bottom:4px;font-weight:700}
    #sift-cur{position:fixed;left:0;top:0;width:22px;height:22px;border-radius:50%;
      background:rgba(255,255,255,.35);border:2px solid #1f6f43;box-shadow:0 2px 10px rgba(0,0,0,.25);
      z-index:2147483646;pointer-events:none;transform:translate(-50%,-50%);
      transition:left .9s cubic-bezier(.22,.8,.26,1), top .9s cubic-bezier(.22,.8,.26,1), width .15s, height .15s}
    #sift-cur.down{width:16px;height:16px;background:rgba(31,111,67,.55)}
    #sift-title{position:fixed;inset:0;display:flex;flex-direction:column;justify-content:center;
      align-items:center;background:rgba(244,240,230,.97);z-index:2147483645;opacity:0;
      transition:opacity .6s ease;pointer-events:none;font-family:"Segoe UI",system-ui,sans-serif;color:#1d2a22}
    #sift-title.on{opacity:1}
    #sift-title h1{font-size:64px;margin:0 0 10px;font-weight:700;letter-spacing:-.02em}
    #sift-title p{font-size:24px;margin:4px 0;color:#3f5247;max-width:900px;text-align:center;line-height:1.45}`;
  const add = () => {
    if (!document.head || !document.body || document.getElementById('sift-cap')) return;
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
    const c = document.createElement('div'); c.id = 'sift-cap'; document.body.appendChild(c);
    const u = document.createElement('div'); u.id = 'sift-cur';
    let p = [720, 450]; try { p = JSON.parse(sessionStorage.getItem('siftCur') || '[720,450]'); } catch (e) {}
    u.style.left = p[0] + 'px'; u.style.top = p[1] + 'px'; document.body.appendChild(u);
    const t = document.createElement('div'); t.id = 'sift-title'; document.body.appendChild(t);
  };
  window.__cap = (html) => { add(); const c = document.getElementById('sift-cap');
    if (!html) { c.classList.remove('on'); return; }
    c.classList.remove('on'); setTimeout(() => { c.innerHTML = html; c.classList.add('on'); }, html && c.innerHTML ? 250 : 0); };
  window.__cur = (x, y, down) => { add(); const u = document.getElementById('sift-cur');
    if (!u) return; u.style.left = x + 'px'; u.style.top = y + 'px'; u.classList.toggle('down', !!down);
    try { sessionStorage.setItem('siftCur', JSON.stringify([x, y])); } catch (e) {} };
  window.__title = (html) => { add(); const t = document.getElementById('sift-title');
    if (!t) return; if (!html) { t.classList.remove('on'); return; } t.innerHTML = html; t.classList.add('on'); };
  window.__cap0 = window.__cap;
  window.__cap = (h) => { add(); const c = document.getElementById('sift-cap'); if (!c) return; window.__cap0(h); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
  try { new MutationObserver(add).observe(document, {childList: true, subtree: true}); } catch (e) {}
})();
"""


class Demo:
    def __init__(self, page):
        self.page = page
        self.t0 = time.monotonic()
        self.cuts: list[dict] = []

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def wait(self, s: float):
        self.page.wait_for_timeout(int(s * 1000))

    def cap(self, html: str | None, hold: float = 0):
        self.page.evaluate("h => window.__cap && window.__cap(h)", html)
        if hold:
            self.wait(hold)

    def title(self, html: str | None, hold: float = 0):
        self.page.evaluate("h => window.__title && window.__title(h)", html)
        if hold:
            self.wait(hold)

    def goto(self, path: str, settle: float = 1.2):
        self.page.goto(BASE + path, wait_until="networkidle", timeout=240_000)
        self.wait(settle)

    def point(self, locator, click: bool = True):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.evaluate("([x,y]) => window.__cur(x,y,false)", [x, y])
        self.page.mouse.move(x, y, steps=25)
        self.wait(1.0)
        if click:
            self.page.evaluate("([x,y]) => window.__cur(x,y,true)", [x, y])
            self.wait(0.18)
            locator.click()
            self.page.evaluate("([x,y]) => window.__cur && window.__cur(x,y,false)", [x, y])

    def scroll(self, pixels: int, seconds: float = 2.5, selector: str | None = None):
        """The browser's own smooth scroll, on the page or on a scrolling panel."""
        self.page.evaluate(
            """([px, sel]) => {
                 const el = sel ? document.querySelector(sel) : null;
                 (el || window).scrollBy({top: px, behavior: 'smooth'});
               }""", [pixels, selector])
        self.wait(seconds)

    def scroll_top(self, seconds: float = 1.6):
        self.page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        self.wait(seconds)


def run():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=str(OUT), record_video_size={"width": W, "height": H})
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        page.set_default_timeout(240_000)
        page.set_default_navigation_timeout(240_000)
        d = Demo(page)

        # 1. Title, over the real empty dashboard
        d.goto("/")
        d.title("<h1>Sift on Akamai Cloud</h1><p>Food-recall pull sheets for school kitchens</p>"
                "<p style='font-size:19px;margin-top:22px'>Live recording of the deployed app &middot; "
                "Linode &middot; Managed PostgreSQL + pgvector &middot; Object Storage &middot; Akamai Inference</p>", 6)
        d.title(None, 1.2)
        d.cap("<span class='k'>The problem</span>A recall lands. The kitchen has <b>24 hours</b> to notify its "
              "distributor and <b>48</b> to finish checking inventory, usually by reading notices against a spreadsheet by hand.", 6.5)
        d.cap("<span class='k'>Before any data</span>Sift does not say &ldquo;all clear&rdquo; when it has seen nothing. "
              "It says no inventory has been received.", 5)

        # 2. Upload the kitchen's export
        d.point(page.get_by_label("Add inventory").first)
        page.wait_for_url("**/ingest", timeout=30_000)
        d.wait(1.2)
        d.cap("<span class='k'>Input</span>The kitchen's ordinary inventory export: <b>56 rows</b> from its "
              "ordering software. Nothing to set up.", 4.5)
        upload = page.get_by_role("button").filter(has_text="Choose a file").first
        if upload.count():
            d.point(upload, click=False)
        with page.expect_response(lambda r: "/api/v1/ingest/upload" in r.url, timeout=180_000):
            page.locator("input[type=file]").set_input_files(str(ROOT / "data/fixtures/inventory_lincoln.csv"))
            d.cap("<span class='k'>Matching</span>Every line is checked against <b>1,012 FDA and USDA recall records</b> "
              "stored in <b>Akamai Managed PostgreSQL</b>. The original file is archived to <b>Akamai Object Storage</b>.")
        d.wait(5)

        # 3. The result
        d.goto("/", settle=1.5)
        d.cap("<span class='k'>Result</span><b>42 items to pull</b>. Both USDA clocks start from when this kitchen "
              "saw the recall.", 6)
        d.point(page.get_by_text("Open sheet").first)
        page.wait_for_url("**/sheet", timeout=30_000)
        d.wait(1.5)
        d.cap("<span class='k'>The pull sheet</span>What to pull, where it is, and why. Class I first, grouped by storage location.", 4)
        d.scroll(500, 2.6)
        d.scroll(500, 2.6)
        d.scroll_top()
        line = page.get_by_role("button").filter(has_text="GROUND BEEF 80/20").first
        d.point(line)
        d.wait(1.5)
        d.cap("<span class='k'>Evidence</span>Each line shows <b>both records verbatim</b>, the inventory row and the "
              "agency's recall, with the text that triggered the match.", 7)
        d.cap("<span class='k'>The safety rule</span>A line is <b>PULL</b> or <b>HELD</b>, enforced by a database constraint. "
              "Nothing can clear itself; a held line waits for a named person.", 6.5)

        # 4. Object Storage: the original file
        d.cap("<span class='k'>Akamai Object Storage</span>The exact file this run read, opened through a presigned link that expires in one hour.")
        d.wait(2)
        d.goto("/files/run/1", settle=1.0)
        d.cap("<span class='k'>Akamai Object Storage</span>Served from <b>us-ord-10.linodeobjects.com</b>. The bucket is private, "
              "and its access key can reach only this bucket.", 6)

        # 5. The next day's export adds one unbranded item
        d.goto("/ingest")
        d.cap("<span class='k'>Next morning</span>Next morning's export arrives. Same kitchen, plus one new line: an "
              "<b>unbranded chickpea dip</b>.", 4)
        with page.expect_response(lambda r: "/api/v1/ingest/upload" in r.url, timeout=180_000):
            page.locator("input[type=file]").set_input_files(str(ROOT / "data/demo/inventory_lincoln_day2.csv"))
        d.wait(3.5)

        # 6. AI: reading order for held lines
        d.cap("<span class='k'>Akamai Inference</span>Sift holds anything it cannot prove, so <b>827 lines</b> are held. "
              "Which should a person read first?", 4.5)
        d.goto("/ai/triage", settle=1.5)
        d.cap("<span class='k'>qwen3-embedding-8b + pgvector</span>Every held pair is embedded and ranked by meaning in one PostgreSQL query. "
              "<b>qwen3-8-27b</b> then reads the closest 36.", 7)
        tally = page.locator(".tally").first
        if tally.count():
            tally.scroll_into_view_if_needed()
            d.scroll(-120, 1.2)
        d.cap("<span class='k'>The result</span>Sliced turkey breast reads as the <b>same product</b> as a Class I recall. "
              "The chickpea dip is a <b>maybe</b> for the Sabra hummus recall, because its brand is missing.", 8)
        d.scroll(380, 2.6)
        d.cap("<span class='k'>Checked, never cleared</span>Each verdict quotes the words that decide it. A &ldquo;different&rdquo; "
              "reading only lowers a line in the order. The line stays HELD.", 7)
        d.scroll_top()

        # 7. AI: a photo of a case label
        d.goto("/ai/label")
        d.cap("<span class='k'>gemma-4-26b-a4b-it &middot; vision</span>In the walk-in, photograph a case label.", 3.5)
        page.locator("input[type=file]").set_input_files(str(ROOT / "data/demo/case_label_hummus.png"))
        d.wait(1)
        d.point(page.get_by_role("button", name="Read it"))
        page.wait_for_load_state("networkidle", timeout=180_000)
        d.wait(1.5)
        d.cap("<span class='k'>Vision model reading</span>Product, firm, barcode and lot are read off the photo. "
              "The barcode then gets an <b>exact</b> lookup in the recall corpus.", 5)
        d.scroll(420, 2.6)
        d.cap("<span class='k'>Exact match</span>Barcode <b>0 40822 01749 7</b> matches Class I recall <b>F-2085-2015</b>, Sabra Classic Hummus. "
              "The meaning check agrees.", 7)
        d.scroll_top()

        # 8. AI: the 24-hour distributor notice
        d.goto("/ai/notice")
        d.cap("<span class='k'>The 24-hour clock</span>Draft the distributor notification from the pull lines.", 3.5)
        cut = {"start": d.now()}
        d.point(page.get_by_role("button", name="Draft the notices"))
        d.cap("<span class='k'>qwen3-8-27b &middot; drafting</span>One email per distributor. The model writes only the subject, "
              "the opening and the closing.")
        page.wait_for_load_state("networkidle", timeout=300_000)
        page.wait_for_selector("text=/from the database|check before sending/i", timeout=300_000)
        cut["end"] = d.now()
        d.cuts.append(cut)
        d.wait(1.2)
        d.cap("<span class='k'>The model writes no data</span>The item table (product, item code, quantity, lot, recall) and the "
              "requested action are built <b>straight from the database</b>.", 7)
        d.cap("<span class='k'>Checked</span>Then a check confirms the model's own words add no number, code, product name or "
              "instruction. If they do, the draft is marked <b>check before sending</b>.", 7)
        d.scroll(520, 3)
        d.scroll(520, 3)
        d.cap("<span class='k'>A person sends it</span>Sift drafts and checks the email, but never sends it.", 4.5)
        d.scroll_top()

        # 9. Close on the services
        d.goto("/health", settle=0.8)
        d.cap("<span class='k'>Running on Akamai Cloud</span>A Linode serving Sift's dashboard &middot; Managed PostgreSQL with pgvector "
              "&middot; Object Storage &middot; Akamai Inference (3 models).", 6)
        d.cap(None, 0.6)
        d.goto("/", settle=0.8)
        d.title("<h1>Sift</h1><p>From the export a kitchen already has, to a pull sheet and a drafted notice, "
                "with every line's evidence attached.</p><p style='font-size:19px;margin-top:22px'>"
                "github.com/PranavPrasannaV/sift-akamai</p>", 6)

        video = page.video
        ctx.close()
        browser.close()
        raw = Path(video.path())
        raw.rename(OUT / "raw.webm")
        (OUT / "cuts.json").write_text(json.dumps({"cuts": d.cuts, "total": d.now()}, indent=1))
        print("recorded", OUT / "raw.webm", d.cuts, "total", d.now())


if __name__ == "__main__":
    run()
