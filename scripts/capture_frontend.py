"""Capture screenshots of the Next.js console.

    uvicorn api.main:app --port 8000 &
    cd frontend && npm run dev &
    python scripts/capture_frontend.py

Uses the system Edge install, so no browser download is needed. Playwright is a
docs-only dependency and lives in requirements-dev.txt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "img"

VIEWPORT = {"width": 1500, "height": 980}
SCALE = 2


def capture(base: str, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    problems: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE,
                                color_scheme="dark")
        page.on("console", lambda m: problems.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

        page.goto(f"{base}/", wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(2500)
        path = out_dir / "frontend-overview.png"
        page.screenshot(path=str(path))
        written.append(path)

        page.goto(f"{base}/console", wait_until="networkidle", timeout=90_000)
        # The console fetches the plant model, the run and the holdout bundle.
        page.wait_for_selector("svg[role='img']", timeout=90_000)
        page.wait_for_timeout(3500)
        path = out_dir / "frontend-console.png"
        page.screenshot(path=str(path))
        written.append(path)

        page.screenshot(path=str(out_dir / "frontend-console-full.png"), full_page=True)
        written.append(out_dir / "frontend-console-full.png")

        browser.close()

    if problems:
        print("browser console problems:")
        for line in dict.fromkeys(problems):
            print("   ", line[:160])
    else:
        print("browser console: clean")
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/capture_frontend.py",
                                 description=__doc__)
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    try:
        written = capture(args.base, args.out)
    except Exception as exc:  # noqa: BLE001 - docs tool: report and exit
        print(f"capture failed: {exc}")
        print("Are both servers running? uvicorn api.main:app --port 8000 ; npm run dev")
        return 1

    for path in written:
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
