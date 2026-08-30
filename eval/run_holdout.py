"""Score the sealed holdout scenarios. Refuses to run against an unfrozen config.

    python -m eval.run_holdout

This is the only place holdout numbers are produced. It will not start without
``config/twin.frozen.yaml``, and it hard-fails -- not warns -- if the live
``config/twin.yaml`` no longer hashes to the frozen record, because holdout
figures produced with thresholds tuned after the freeze are not holdout figures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from simulator.config import (HOLDOUT_SEED_RANGE, REPO_ROOT, list_scenarios,
                              load_line_config)
from twin.config import load_twin_config
from twin.thresholds import select_all

from . import freeze_thresholds
from .freeze_thresholds import FreezeError, verify
from .harness import prepare_split
from .matching import load_eval_config
from .metrics import aggregate, score_scenario
from .sweep import sweep, write_csv, write_plot

REPORTS = REPO_ROOT / "reports"


def run(sensitivity: float | None = None, horizon_s: float | None = None,
        force: bool = False, verbose: bool = True) -> dict[str, Any]:
    """Prepare, score and sweep the holdout split. Returns the full result bundle."""
    # Resolve the frozen path at call time rather than binding it as a default,
    # so the location is a single source of truth and can be redirected.
    frozen_path = freeze_thresholds.FROZEN_PATH
    freeze_meta = verify(target=frozen_path)
    twin_cfg = load_twin_config(frozen_path, sensitivity)
    eval_cfg = load_eval_config()
    line = load_line_config()
    scenarios = list_scenarios("holdout")
    if not scenarios:
        raise RuntimeError("no holdout scenarios found in config/scenarios/holdout/")

    if verbose:
        print(f"Frozen config: {freeze_meta['source_sha256'][:16]}... "
              f"(sealed {freeze_meta['frozen_at_utc']})")
        print(f"Holdout scenarios: {len(scenarios)}, seeds "
              f"{HOLDOUT_SEED_RANGE[0]}-{HOLDOUT_SEED_RANGE[1]}")

    results = prepare_split(scenarios, twin_cfg, line, horizon_s=horizon_s,
                            force=force, verbose=verbose)
    scores = [
        score_scenario(r.ground_truth, select_all(r.twin_output, twin_cfg), eval_cfg)
        for r in results
    ]
    summary = aggregate(scores, eval_cfg)
    sweep_rows = sweep(results, twin_cfg, eval_cfg)

    return {
        "freeze": freeze_meta,
        "frozen_config": freeze_thresholds._display_path(frozen_path),
        "sensitivity": twin_cfg.sensitivity,
        "seed_range": list(HOLDOUT_SEED_RANGE),
        "eval_config": {
            "station_tolerance": eval_cfg.station_tolerance,
            "match_margin_s": eval_cfg.match_margin_s,
            "onset_window_s": eval_cfg.onset_window_s,
            "shift_s": eval_cfg.shift_s,
            "sweep_points": eval_cfg.sweep_points,
            "confidence_level": eval_cfg.confidence_level,
        },
        "l3_model": {
            "source": results[0].twin_output["l3_summary"]["model_source"] if results else "none",
            "path": twin_cfg.l3.get("model_path"),
            "trained_on": "tuning split only (see scripts/train_l3.py leakage guard)",
        },
        "scenarios": [s.as_row() for s in scores],
        "queue_formation_sustain_units": next(
            (r.ground_truth["queue_formation_sustain_units"] for r in results
             if "queue_formation_sustain_units" in r.ground_truth), None),
        "summary": summary,
        "sweep": sweep_rows,
        "line": {
            "n_stations": line.n_stations,
            "n_instrumented": len(line.instrumented_ids),
            "uninstrumented": line.uninstrumented_ids,
            "takt_time_s": line.takt_time_s,
        },
    }


def _print_scorecard(bundle: dict[str, Any]) -> None:
    s = bundle["summary"]
    fa = s["false_alarms_per_shift"]
    print("\n" + "=" * 78)
    print(f"HOLDOUT SCORECARD  (sealed scenarios, sensitivity {bundle['sensitivity']})")
    print("=" * 78)
    print(f"{'scenario':32s} {'fam':<9} {'st':>3} {'instr':>5} {'lead':>7} {'onset':>7} {'contain':>8}")
    for row in bundle["scenarios"]:
        lead = f"{row['lead_time_queue_min']:+.0f}" if row["lead_time_queue_min"] is not None else "-"
        onset = f"{row['detection_vs_onset_min']:+.0f}" if row["detection_vs_onset_min"] is not None else "-"
        cont = f"{row['containment_rate']:.0%}" if row["containment_rate"] is not None else "-"
        instr = "-" if row["target_instrumented"] is None else ("yes" if row["target_instrumented"] else "NO")
        print(f"{row['scenario_id']:32s} {row['family']:<9} "
              f"{str(row['target_station'] or '-'):>3} {instr:>5} {lead:>7} {onset:>7} {cont:>8}")
    print("-" * 78)
    print(f"recall {s['n_detected']}/{s['n_faulted']}   precision {_pct(s['precision'])}")
    print(f"median lead time (queue-forming, n={s['queue_forming']['n']}): "
          f"{_num(s['queue_forming']['median_lead_time_min'])} min early")
    print(f"median detection vs onset (non-queue-forming, n={s['non_queue_forming']['n']}): "
          f"{_num(s['non_queue_forming']['median_detection_vs_onset_min'])} min")
    print(f"containment (quality faults, n={s['quality']['n']}): "
          f"{_pct(s['quality']['mean_containment_rate'])} "
          f"({s['quality']['total_contained']}/{s['quality']['total_affected']} units)")
    ci = "" if fa["low"] is None else f"  95% CI [{fa['low']:.2f}, {fa['high']:.2f}]"
    print(f"false alarms/shift (controls only, n={fa['n']}): {_num(fa['mean'], 2)}{ci}")
    print("=" * 78)


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}" if digits == 1 else f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.run_holdout", description=__doc__)
    ap.add_argument("--sensitivity", type=float, default=None,
                    help="override the frozen master sensitivity for the headline table")
    ap.add_argument("--horizon", type=float, default=None, help="shorten the sim horizon (smoke runs)")
    ap.add_argument("--force", action="store_true", help="ignore cached runs and recompute")
    ap.add_argument("--out", type=Path, default=REPORTS, help="report directory")
    args = ap.parse_args(argv)

    try:
        bundle = run(args.sensitivity, args.horizon, args.force)
    except FreezeError as exc:
        print(f"\nREFUSING TO SCORE\n{exc}\n")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "holdout_results.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8", newline="\n")
    write_csv(bundle["sweep"], args.out / "threshold_sweep.csv")
    write_plot(bundle["sweep"], args.out / "threshold_sweep.html",
               "Ninja threshold sweep (sealed holdout scenarios)")

    _print_scorecard(bundle)
    print(f"\nwrote {args.out / 'holdout_results.json'}")
    print(f"wrote {args.out / 'threshold_sweep.csv'}")
    print(f"wrote {args.out / 'threshold_sweep.html'}")
    print("run `python -m eval.report` to render reports/holdout_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
