"""Ninja end-to-end demo. No UI required.

    python run_demo.py            # 2 shifts (15 h) simulated, ~30 s wall clock
    python run_demo.py --fast     # short smoke run
    python run_demo.py --holdout  # score the sealed holdout split instead

Runs simulator -> twin -> eval for a small demo set and prints the scorecard to
stdout. The demo set is drawn from the **tuning** split, so these are development
figures; the validated numbers live in `reports/holdout_report.md` and are
produced by `python -m eval.run_holdout` against a frozen config.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.harness import prepare_split  # noqa: E402
from eval.matching import load_eval_config  # noqa: E402
from eval.metrics import aggregate, score_scenario  # noqa: E402
from simulator.config import list_scenarios, load_line_config  # noqa: E402
from twin.config import load_twin_config  # noqa: E402
from twin.thresholds import select_all, station_alerts  # noqa: E402

DEMO_SCENARIOS = (
    "tuning_drift_s12",           # instrumented bottleneck drift
    "tuning_drift_s27_uninstr",   # drift at a station with no sensors at all
    "tuning_quality_s08",         # defect escape, surfaces only at final inspection
    "tuning_control_a",           # no fault: every alert here is a false alarm
)
FAST_HORIZON_S = 21600.0   # 6 h
DEMO_HORIZON_S = 54000.0   # 2 shifts
RULE = "=" * 84


def _hms(seconds: float) -> str:
    return f"{seconds / 3600.0:5.2f} h"


def _print_line_summary(line) -> None:
    print(RULE)
    print("Ninja — digital twin of a mixed-model vehicle assembly line")
    print(RULE)
    uninstr = line.uninstrumented_ids
    print(f"  stations          : {line.n_stations} "
          f"(body 1-15, paint 16-24, final assembly 25-40)")
    print(f"  instrumented      : {len(line.instrumented_ids)}/{line.n_stations} "
          f"({len(line.instrumented_ids) / line.n_stations:.0%}) — the rest emit nothing per unit")
    print(f"  uninstrumented    : {', '.join(str(s) for s in uninstr)}")
    print(f"  takt              : {line.takt_time_s:.1f} s      "
          f"buffers: {min(s.buffer_capacity for s in line.stations.values())}"
          f"-{max(s.buffer_capacity for s in line.stations.values())} units")
    print("  buffer levels are NEVER emitted; the twin infers them from flow.")


def _print_scenario(result, score, alerts, line) -> None:
    gt = result.ground_truth
    print("\n" + "-" * 84)
    print(f"  {result.scenario.scenario_id}   ({result.scenario.description})")
    print("-" * 84)
    if gt["fault"]["family"] == "none":
        print("  injected fault    : none (control run)")
    else:
        st = gt["target_station"]
        seen = "instrumented" if gt["target_station_instrumented"] else "UNINSTRUMENTED"
        print(f"  injected fault    : {gt['fault']['family']} at station {st} ({seen}), "
              f"onset {gt['onset_s'] / 60:.0f} min")
    if gt["queue_forming"]:
        print(f"  ground truth      : buffer {gt['queue_formation_buffer']} saturated at "
              f"{gt['queue_formation_ts'] / 60:.0f} min "
              f"({gt['throughput_loss_units']} units lost vs the counterfactual)")
    elif gt["fault"]["family"] != "none":
        print("  ground truth      : no fault-attributable queue formed "
              "(scored against onset instead)")

    print(f"  twin alerts       : L1 {len(alerts['l1'])}  L2 {len(alerts['l2'])}  "
          f"L3 {len(alerts['l3'])}")

    if score.detected:
        if score.lead_time_queue_min is not None:
            print(f"  >> LEAD TIME      : {score.lead_time_queue_min:+.1f} min before the "
                  f"queue formed  (first alert: {score.first_alert_layer}/"
                  f"{score.first_alert_signal})")
        else:
            print(f"  >> DETECTION      : {score.detection_vs_onset_min:+.1f} min vs onset "
                  f"(onset-relative; no queue to beat)  (first alert: "
                  f"{score.first_alert_layer}/{score.first_alert_signal})")
    elif gt["fault"]["family"] != "none":
        print("  >> NOT DETECTED")

    if score.containment_rate is not None:
        print(f"  >> CONTAINMENT    : {score.containment_rate:.1%} "
              f"({score.n_contained}/{score.n_affected} affected units flagged before "
              f"their own inspection, median {score.units_early_min:.0f} min early)")

    if gt["fault"]["family"] == "none":
        shifts = gt["horizon_s"] / 27000.0
        print(f"  >> FALSE ALARMS   : {len(alerts['l1']) + len(alerts['l2'])} over "
              f"{shifts:.1f} shifts = "
              f"{(len(alerts['l1']) + len(alerts['l2'])) / shifts:.2f} per shift")

    ranked = station_alerts(result.twin_output, load_twin_config())[:1]
    if ranked:
        top = ranked[0]
        ev = top["evidence"]
        print(f"  top alert         : {top['layer']} station {top.get('station')} "
              f"({top.get('signal') or top.get('kind')}) at {top['ts'] / 60:.0f} min, "
              f"confidence {top['confidence_label']}")
        keys = [k for k in ("baseline_mean", "current_value", "cusum_stat",
                            "cause_cycle_estimate_s", "rate_deficit_per_s",
                            "time_to_event_min", "estimate_basis", "sample_count")
                if k in ev]
        print("    evidence        : " + ", ".join(f"{k}={ev[k]}" for k in keys))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python run_demo.py", description=__doc__)
    ap.add_argument("--fast", action="store_true", help="short smoke run (6 h simulated)")
    ap.add_argument("--holdout", action="store_true",
                    help="score the sealed holdout split instead of the demo set")
    ap.add_argument("--sensitivity", type=float, default=None, help="override master sensitivity")
    ap.add_argument("--force", action="store_true", help="ignore cached runs")
    args = ap.parse_args(argv)

    if args.holdout:
        from eval.run_holdout import main as holdout_main
        return holdout_main([] if args.sensitivity is None
                            else ["--sensitivity", str(args.sensitivity)])

    started = time.time()
    horizon = FAST_HORIZON_S if args.fast else DEMO_HORIZON_S
    line = load_line_config()
    twin_cfg = load_twin_config(sensitivity=args.sensitivity)
    eval_cfg = load_eval_config()

    _print_line_summary(line)
    print(f"  horizon           : {_hms(horizon)} simulated"
          f"{'  (--fast smoke run)' if args.fast else '  (2 shifts)'}")
    print(f"  sensitivity       : {twin_cfg.sensitivity}")
    print("\n  Scenarios are from the TUNING split — these are development figures.")
    print("  Validated numbers: python -m eval.run_holdout  ->  reports/holdout_report.md")

    wanted = {s.scenario_id: s for s in list_scenarios("tuning")}
    scenarios = [wanted[name] for name in DEMO_SCENARIOS if name in wanted]
    print(f"\nRunning {len(scenarios)} scenarios (simulate -> counterfactual -> twin -> score) ...")
    results = prepare_split(scenarios, twin_cfg, line, horizon_s=horizon,
                            force=args.force, verbose=True)

    scores = []
    for result in results:
        alerts = select_all(result.twin_output, twin_cfg)
        score = score_scenario(result.ground_truth, alerts, eval_cfg)
        scores.append(score)
        _print_scenario(result, score, alerts, line)

    summary = aggregate(scores, eval_cfg)
    fa = summary["false_alarms_per_shift"]
    print("\n" + RULE)
    print("DEMO SCORECARD (tuning split)")
    print(RULE)
    print(f"  faults detected            : {summary['n_detected']}/{summary['n_faulted']}")
    print(f"  alert precision            : {summary['precision']:.1%}"
          if summary["precision"] is not None else "  alert precision            : n/a")
    q = summary["queue_forming"]
    if q["median_lead_time_min"] is not None:
        print(f"  median lead time           : {q['median_lead_time_min']:+.1f} min "
              f"before queue formation (n={q['n']}, positive = early)")
    nq = summary["non_queue_forming"]
    if nq["median_detection_vs_onset_min"] is not None:
        print(f"  median detection vs onset  : {nq['median_detection_vs_onset_min']:+.1f} min "
              f"(n={nq['n']}, non-queue-forming faults, reported separately)")
    qual = summary["quality"]
    if qual["mean_containment_rate"] is not None:
        print(f"  defect containment         : {qual['mean_containment_rate']:.1%} "
              f"({qual['total_contained']}/{qual['total_affected']} units, "
              f"median {qual['median_units_early_min']:.0f} min early)")
    if fa["mean"] is not None:
        print(f"  false alarms per shift     : {fa['mean']:.2f} "
              f"(control runs only, n={fa['n']})")
    print(f"  throughput lost to faults  : {summary['throughput_loss_units_total']} units")
    print(f"\n  wall clock: {time.time() - started:.1f} s")
    print(RULE)
    print("  Next:  streamlit run app/streamlit_app.py     (supervisor / plant / validation UI)")
    print("         python -m eval.run_holdout             (sealed holdout scorecard)")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
