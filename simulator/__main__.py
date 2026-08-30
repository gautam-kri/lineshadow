"""CLI: run one scenario (or a whole split) and write its run directory.

    python -m simulator --scenario config/scenarios/tuning/tuning_drift_s12.yaml
    python -m simulator --split holdout --horizon 14400
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import Scenario, list_scenarios, load_line_config, load_scenario
from .runner import RUNS_ROOT, run_scenario


def _summarise(scenario: Scenario, gt: dict) -> str:
    qf = gt["queue_formation_ts"]
    queue = f"{qf / 60.0:8.1f} min" if qf is not None else "     none"
    return (f"{scenario.scenario_id:32s} seed={scenario.seed:<5d} "
            f"family={gt['fault']['family']:<9s} queue_formation={queue} "
            f"throughput_loss={gt['throughput_loss_units']:3d} units")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m simulator", description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--scenario", type=Path, help="path to a scenario YAML")
    src.add_argument("--split", choices=("tuning", "holdout"), help="run a whole split")
    ap.add_argument("--seed", type=int, default=None,
                    help="override the scenario seed (must stay in the split's range)")
    ap.add_argument("--horizon", type=float, default=None, help="override horizon, seconds")
    ap.add_argument("--out", type=Path, default=RUNS_ROOT, help="output root (default: runs/)")
    ap.add_argument("--line", type=Path, default=None, help="line config (default: config/line.yaml)")
    args = ap.parse_args(argv)

    line = load_line_config(args.line) if args.line else load_line_config()
    scenarios = [load_scenario(args.scenario)] if args.scenario else list_scenarios(args.split)
    if args.seed is not None:
        if len(scenarios) > 1:
            ap.error("--seed only makes sense with a single --scenario")
        scenarios = [replace(scenarios[0], seed=args.seed)]

    print(f"Ninja simulator: {len(scenarios)} scenario(s), line={line.n_stations} stations, "
          f"{len(line.instrumented_ids)} instrumented")
    for sc in scenarios:
        art = run_scenario(sc, line, out_root=args.out, horizon_s=args.horizon)
        print(_summarise(sc, art.ground_truth), f"-> {art.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
