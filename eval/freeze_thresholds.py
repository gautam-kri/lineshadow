"""Freeze protocol: seal the twin config before any holdout scenario is scored.

``config/twin.frozen.yaml`` is a byte-for-byte copy of ``config/twin.yaml`` with a
``freeze:`` block recording when it was sealed and the SHA-256 of the source it
was sealed from. ``eval/run_holdout.py`` refuses to run without it and hard-fails
if the live config no longer hashes to the recorded value.

The freeze is the integrity claim behind every holdout number, so it is enforced,
not advisory.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

import yaml

from twin.config import DEFAULT_TWIN_CONFIG, REPO_ROOT, config_hash

FROZEN_PATH = REPO_ROOT / "config" / "twin.frozen.yaml"


class FreezeError(RuntimeError):
    """Raised when the frozen config is missing or no longer matches the live one."""


def _display_path(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise (tests seal temp files)."""
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def freeze(source: Path | None = None, target: Path | None = None,
           note: str = "") -> dict[str, Any]:
    """Seal ``source`` into ``target``. Returns the freeze metadata."""
    source = source or DEFAULT_TWIN_CONFIG
    target = target or FROZEN_PATH
    source_bytes = source.read_bytes()
    meta = {
        "frozen_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": _display_path(source),
        "source_sha256": config_hash(source),
        "note": note,
    }
    header = (
        "# FROZEN TWIN CONFIGURATION -- do not hand-edit.\n"
        "# Written by eval/freeze_thresholds.py. Every number in\n"
        "# reports/holdout_report.md was produced with exactly these thresholds.\n"
        "# To retune, edit config/twin.yaml and re-freeze; the holdout run will\n"
        "# refuse to score until the two hashes agree again.\n\n"
    )
    target.write_text(
        header + yaml.safe_dump({"freeze": meta}, sort_keys=False) + "\n"
        + source_bytes.decode("utf-8"),
        encoding="utf-8", newline="\n",
    )
    return meta


def read_freeze_metadata(target: Path | None = None) -> dict[str, Any]:
    """Read the ``freeze:`` block from the frozen config."""
    target = target or FROZEN_PATH
    if not target.exists():
        raise FreezeError(
            f"{target} does not exist. Run `python -m eval.freeze_thresholds` to seal "
            "the current thresholds before scoring any holdout scenario."
        )
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "freeze" not in raw or "twin" not in raw:
        raise FreezeError(f"{target} is not a valid frozen config (missing freeze/twin blocks)")
    return raw["freeze"]


def verify(source: Path | None = None, target: Path | None = None) -> dict[str, Any]:
    """Hard-fail unless the live config still hashes to the frozen record."""
    source = source or DEFAULT_TWIN_CONFIG
    target = target or FROZEN_PATH
    meta = read_freeze_metadata(target)
    live = config_hash(source)
    if live != meta["source_sha256"]:
        raise FreezeError(
            "FROZEN CONFIG MISMATCH -- refusing to score.\n"
            f"  frozen at : {meta['frozen_at_utc']}\n"
            f"  frozen from: {meta['source']} sha256={meta['source_sha256']}\n"
            f"  live       : {source} sha256={live}\n"
            "The twin config changed after the thresholds were frozen. Either revert "
            "config/twin.yaml, or re-freeze and re-run the whole holdout evaluation. "
            "Reporting holdout numbers from thresholds tuned after the freeze would "
            "not be a holdout result."
        )
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.freeze_thresholds", description=__doc__)
    ap.add_argument("--note", default="", help="free-text note stored with the freeze")
    ap.add_argument("--verify", action="store_true", help="verify instead of re-freezing")
    args = ap.parse_args(argv)

    if args.verify:
        # Report the mismatch as a message and a non-zero exit code, not a
        # traceback: this is the command CI and a reviewer run, and a stack trace
        # buries the one sentence that says what is actually wrong.
        try:
            meta = verify()
        except FreezeError as exc:
            print(f"\n{exc}\n")
            return 2
        print(f"OK: live config matches the freeze from {meta['frozen_at_utc']}")
        print(f"    sha256 {meta['source_sha256']}")
        return 0

    meta = freeze(note=args.note)
    print(f"Froze {meta['source']} -> {FROZEN_PATH.relative_to(REPO_ROOT)}")
    print(f"  frozen_at_utc : {meta['frozen_at_utc']}")
    print(f"  source_sha256 : {meta['source_sha256']}")
    if meta["note"]:
        print(f"  note          : {meta['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
