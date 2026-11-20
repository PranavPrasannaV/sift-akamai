"""Record the benchmark segment of the demo video against the live deployment.

Same overlay and pacing as scripts/record_demo.py. Writes demo/bench_raw.webm and
demo/bench.json (the second the page is ready, so the blank lead-in can be cut).
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.record_demo import H, OUT, OVERLAY, W, Demo


def run():
    tmp = OUT / "bench_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        page.set_default_timeout(120_000)
        d = Demo(page)
        d.goto("/ai/benchmark", settle=0.6)
        start = d.now()
        d.cap("<span class='k'>Benchmark evaluation</span>Measured on the live deployment by <b>scripts/benchmark.py</b>, "
              "against ground truth: the recalled products planted in the export, and the pull lines in the database.", 7)
        d.cap("<span class='k'>The notice: baseline vs new</span>Baseline, the model writes the whole email: <b>57.9 s</b> each and "
              "<b>one invented figure</b>. New, the model writes no data: <b>2.9 s</b>, <b>zero</b> invented, every row correct.", 9)
        d.cap(None, 0.4)
        d.scroll(560, 2.6)
        d.cap("<span class='k'>The held list: baseline vs new</span>Five real recalls are hidden among <b>814 held lines</b>. "
              "In the sheet's own order they sit at a median of <b>406</b>. Embeddings, rank fusion and the model's read bring that to <b>71</b>, "
              "and the turkey to <b>#1</b>.", 10)
        d.cap("<span class='k'>Where it misses</span>The model called the carrots <b>different</b>, so they sit at 28, not 7. "
              "They stay HELD: a verdict only reorders, it never clears.", 8)
        d.cap(None, 0.4)
        d.scroll(520, 2.6)
        d.cap("<span class='k'>Techniques applied</span>Split the work by trust &middot; embeddings in pgvector &middot; "
              "reciprocal rank fusion of rules and meaning &middot; read only the top 36 and cache every verdict.", 8)
        d.cap(None, 0.6)
        d.scroll_top(1.4)
        end = d.now()
        video = page.video
        ctx.close()
        browser.close()
        raw = OUT / "bench_raw.webm"
        if raw.exists():
            raw.unlink()
        Path(video.path()).rename(raw)
        tmp.rmdir()
        (OUT / "bench.json").write_text(json.dumps({"start": start, "end": end}))
        print("recorded", raw, start, end)


if __name__ == "__main__":
    run()
