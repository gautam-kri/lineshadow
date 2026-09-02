"""Bake the API's read-only responses to static JSON for GitHub Pages.

    python scripts/export_static_api.py

GitHub Pages serves static files only, so the hosted console cannot call the
FastAPI engine. This writes the same payloads the API would return into
``frontend/public/api/``, and the client falls back to reading them when
``NEXT_PUBLIC_STATIC_API`` is set at build time.

What survives the bake and what does not:

* Scenario browsing, the line diagram, the alert feed with full evidence, and the
  sensitivity control all work exactly as they do live, because they are reads of
  data the engine already computed.
* The live perturbation panel does **not**, and is not faked. It needs to run a
  new simulation and its counterfactual server-side. The hosted build says so and
  points at the local instructions rather than replaying a canned result --
  pretending otherwise would undo the one claim the panel exists to make.

Sensitivity is baked at the twelve points of the published threshold sweep, and
the static client snaps to the nearest. That is a slightly coarser control than
the live one, and a more honest one: every position now corresponds to a measured
point rather than an interpolation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.harness import prepare_scenario  # noqa: E402
from eval.matching import load_eval_config  # noqa: E402
from eval.metrics import score_scenario  # noqa: E402
from eval.sweep import sensitivity_points  # noqa: E402
from simulator.config import list_scenarios, load_line_config  # noqa: E402
from simulator.runner import RUNS_ROOT  # noqa: E402
from twin.config import load_twin_config  # noqa: E402
from twin.thresholds import select_all, station_alerts  # noqa: E402

OUT_ROOT = REPO_ROOT / "frontend" / "public" / "api"
REPORTS = REPO_ROOT / "reports"


def write(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"))
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(text)


def line_payload(line) -> dict[str, Any]:
    return {
        "n_stations": line.n_stations,
        "takt_time_s": line.takt_time_s,
        "inspection_station": line.inspection_station,
        "zones": {k: list(v) for k, v in line.zones.items()},
        "instrumented_ids": line.instrumented_ids,
        "uninstrumented_ids": line.uninstrumented_ids,
        "stations": [
            {"id": s.id, "name": s.name, "zone": s.zone,
             "nominal_cycle_s": s.mean_cycle_s,
             "buffer_capacity": s.buffer_capacity,
             "instrumented": s.instrumented}
            for s in (line.station(i) for i in line.station_ids)
        ],
    }


def without_evidence(alerts: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Strip evidence from the raw alert arrays.

    The console reads these only for counts and for the station severity / cause
    maps -- never for display. The feed renders `ranked_alerts`, which keeps its
    evidence intact, so nothing the UI can actually open loses its audit trail.

    Truncating `ranked_alerts` instead would be a mistake: the client groups
    repeats into one row per issue, and the highest-scoring alerts are all the
    same re-firing station, so cutting the list before grouping collapses the
    whole feed into a single row.
    """
    return {
        layer: [{k: v for k, v in row.items() if k != "evidence"} for row in rows]
        for layer, rows in alerts.items()
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/export_static_api.py",
                                 description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--clean", action="store_true", help="wipe the output directory first")
    args = ap.parse_args(argv)

    if args.clean and args.out.exists():
        shutil.rmtree(args.out)

    line = load_line_config()
    cfg = load_twin_config()
    eval_cfg = load_eval_config()
    scenarios = list_scenarios("tuning") + list_scenarios("holdout")
    points = sensitivity_points(eval_cfg.sweep_points)

    total = 0
    total += write(args.out / "line.json", line_payload(line))
    total += write(args.out / "scenarios.json", [
        {"scenario_id": s.scenario_id, "split": s.split, "seed": s.seed,
         "horizon_s": s.horizon_s, "family": s.family,
         "target_station": s.target_station, "description": s.description}
        for s in scenarios
    ])

    holdout_path = REPORTS / "holdout_results.json"
    if not holdout_path.exists():
        print("holdout_results.json missing; run `python -m eval.run_holdout` first")
        return 1
    total += write(args.out / "holdout.json", json.loads(holdout_path.read_text(encoding="utf-8")))
    total += write(args.out / "sensitivities.json", points)

    for scenario in scenarios:
        result = prepare_scenario(scenario, line, cfg, RUNS_ROOT)
        print(f"  {scenario.scenario_id} ...", end="", flush=True)
        scenario_bytes = 0
        for index, s in enumerate(points):
            alerts = select_all(result.twin_output, cfg, s)
            ranked = station_alerts(result.twin_output, cfg, s)
            payload = {
                "scenario_id": scenario.scenario_id,
                "split": scenario.split,
                "sensitivity": s,
                "thresholds": {"l1": cfg.l1_threshold(s), "l2": cfg.l2_threshold(s),
                               "l3": cfg.l3_threshold(s)},
                # Sensitivity-independent, but repeated so one fetch serves a
                # render. It is 13 KB and avoids a second round trip per change.
                "stations": result.twin_output["stations"],
                "alerts": without_evidence(alerts),
                "ranked_alerts": ranked,
                "ground_truth": result.ground_truth,
                "score": score_scenario(result.ground_truth, alerts, eval_cfg).as_row(),
                "static": True,
            }
            scenario_bytes += write(
                args.out / "run" / scenario.scenario_id / f"{index}.json", payload)
        total += scenario_bytes
        print(f" {scenario_bytes / 1024:6.0f} KB")

    files = sum(1 for _ in args.out.rglob("*.json"))
    print(f"\nwrote {files} files, {total / 1024 / 1024:.2f} MB total -> "
          f"{args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
