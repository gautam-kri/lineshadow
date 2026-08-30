"""CLI: run the twin against an event stream.

    python -m twin --events runs/<run_id>/events.jsonl --out runs/<run_id>

Reads only the event stream and the plant/twin configs. It never opens
``ground_truth.json`` -- ``tests/test_isolation.py`` proves that by running this
entrypoint in a directory where that file does not exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulator.config import load_line_config

from .config import load_twin_config
from .thresholds import select_all
from .twin import DigitalTwin, stream_events


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin", description=__doc__)
    ap.add_argument("--events", required=True, type=Path, help="path to events.jsonl")
    ap.add_argument("--out", type=Path, default=None, help="directory for twin_output.json")
    ap.add_argument("--config", type=Path, default=None, help="twin config (default: config/twin.yaml)")
    ap.add_argument("--line", type=Path, default=None, help="line config (default: config/line.yaml)")
    ap.add_argument("--sensitivity", type=float, default=None, help="override master sensitivity")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    line = load_line_config(args.line) if args.line else load_line_config()
    cfg = load_twin_config(args.config, args.sensitivity) if args.config \
        else load_twin_config(sensitivity=args.sensitivity)

    twin = DigitalTwin(line, cfg)
    output = twin.run(stream_events(str(args.events)))
    alerts = select_all(output, cfg)
    output["alerts_at_configured_sensitivity"] = alerts

    out_dir = args.out or args.events.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "twin_output.json"
    path.write_text(json.dumps(output, indent=1), encoding="utf-8", newline="\n")

    if not args.quiet:
        print(f"events={output['meta']['n_events']} "
              f"L1 candidates={len(output['l1_candidates'])} alerts={len(alerts['l1'])} "
              f"L2 candidates={len(output['l2_candidates'])} alerts={len(alerts['l2'])} "
              f"L3 candidates={len(output['l3_candidates'])} alerts={len(alerts['l3'])}")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
