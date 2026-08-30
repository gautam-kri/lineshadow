"""Capture the README screenshots from the live app.

    streamlit run app/streamlit_app.py --server.port 8511 &
    python scripts/capture_screenshots.py

Drives the real Streamlit console with Playwright and writes PNGs to docs/img/,
so every image in the README is a genuine screenshot of the running product and
can be regenerated on demand rather than drifting out of date.

Uses the system Edge install (``channel="msedge"``), so no browser download is
needed. Playwright is a docs-only dependency and lives in requirements-dev.txt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "img"

VIEWPORT = {"width": 1500, "height": 950}
SCALE = 2  # retina-quality output


def _settle(page, seconds: float = 2.5) -> None:
    """Wait for Streamlit to finish its rerun and for charts to paint."""
    page.wait_for_timeout(int(seconds * 1000))


def _select_tab(page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    _settle(page, 3.0)


def _scroll_to_heading(page, name: str) -> None:
    """Bring a section heading into view.

    Streamlit renders each heading twice (the visible one plus an anchor), so the
    locator is narrowed by role and takes the first match to stay out of strict mode.
    """
    page.get_by_role("heading", name=name).first.scroll_into_view_if_needed()


def capture(url: str, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE,
                                color_scheme="dark")
        page.goto(url, wait_until="networkidle", timeout=120_000)
        page.wait_for_selector('button[role="tab"]', timeout=120_000)
        _settle(page, 6.0)

        # 1. Supervisor: the line state, which is the product's signature view.
        path = out_dir / "supervisor.png"
        page.screenshot(path=str(path))
        written.append(path)

        # 2. The alert feed with one alert expanded, showing its evidence. Streamlit
        # scrolls an inner container rather than the window, so scroll the element
        # into view instead of turning the mouse wheel at the page.
        expander = page.locator('[data-testid="stExpander"]').first
        expander.locator("summary").click()
        _settle(page, 2.0)
        expander.scroll_into_view_if_needed()
        _settle(page, 1.5)
        path = out_dir / "alert-evidence.png"
        page.screenshot(path=str(path))
        written.append(path)

        # 3. Plant manager: buffer pressure heatmap and defect Pareto.
        _select_tab(page, "Plant manager")
        _scroll_to_heading(page, "Buffer pressure")
        _settle(page, 2.5)
        path = out_dir / "plant-manager.png"
        page.screenshot(path=str(path))
        written.append(path)

        # 4. Validation: the threshold sweep and the live perturbation panel.
        _select_tab(page, "Validation")
        _scroll_to_heading(page, "Threshold sweep")
        _settle(page, 2.5)
        path = out_dir / "validation.png"
        page.screenshot(path=str(path))
        written.append(path)

        # 5. A live perturbation actually executed: fresh simulation, fresh
        # counterfactual, twin re-run and re-scored, all triggered from the UI.
        page.get_by_role("button", name="Run scenario").click()
        page.wait_for_timeout(20_000)
        _scroll_to_heading(page, "Live perturbation")
        _settle(page, 2.0)
        path = out_dir / "live-perturbation.png"
        page.screenshot(path=str(path))
        written.append(path)

        browser.close()
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/capture_screenshots.py",
                                 description=__doc__)
    ap.add_argument("--url", default="http://localhost:8511")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    try:
        written = capture(args.url, args.out)
    except Exception as exc:  # noqa: BLE001 - this is a docs tool, report and exit
        print(f"capture failed: {exc}")
        print("Is the app running?  streamlit run app/streamlit_app.py --server.port 8511")
        return 1

    for path in written:
        size_kb = path.stat().st_size / 1024
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
