"""Running scenarios through simulator -> twin, with on-disk caching.

The twin is run **once** per scenario, at the sensitivity-1 emission floor. Every
sensitivity in the threshold sweep is then a filter over those cached candidates
rather than a re-run. That is what keeps a 12-point sweep across a dozen
scenarios inside a sane runtime, and it is also why the sweep's monotonicity is
exact rather than approximate: all sensitivities see the identical candidate set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from simulator.config import LineConfig, Scenario, load_line_config
from simulator.runner import RUNS_ROOT, run_scenario
from twin.config import TwinConfig, config_hash
from twin.twin import DigitalTwin, stream_events


@dataclass
class ScenarioResult:
    """One scenario, its hidden ground truth, and what the twin produced."""

    scenario: Scenario
    ground_truth: dict[str, Any]
    twin_output: dict[str, Any]
    run_dir: Path

    @property
    def is_control(self) -> bool:
        return self.scenario.family == "none"


def _cache_key(cfg: TwinConfig, horizon_s: float | None) -> dict[str, Any]:
    return {
        "twin_config_sha256": config_hash(cfg.source_path) if cfg.source_path else None,
        "horizon_s": horizon_s,
    }


def prepare_scenario(scenario: Scenario, line: LineConfig, cfg: TwinConfig,
                     out_root: Path = RUNS_ROOT, horizon_s: float | None = None,
                     force: bool = False) -> ScenarioResult:
    """Simulate (if needed), run the twin (if needed), and return both sides."""
    run_dir = Path(out_root) / scenario.run_id
    events = run_dir / "events.jsonl"
    gt_path = run_dir / "ground_truth.json"
    horizon = horizon_s if horizon_s is not None else scenario.horizon_s

    stale_sim = force or not events.exists() or not gt_path.exists()
    if not stale_sim:
        recorded = json.loads((run_dir / "scenario.json").read_text(encoding="utf-8"))
        stale_sim = abs(float(recorded["horizon_s"]) - horizon) > 1e-6
    if stale_sim:
        run_scenario(scenario, line, out_root=out_root, horizon_s=horizon)

    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))

    key = _cache_key(cfg, horizon)
    twin_path = run_dir / "twin_output.json"
    cached: dict[str, Any] | None = None
    if not force and twin_path.exists():
        try:
            candidate = json.loads(twin_path.read_text(encoding="utf-8"))
            if candidate.get("meta", {}).get("cache_key") == key:
                cached = candidate
        except (json.JSONDecodeError, OSError):
            cached = None

    if cached is None:
        output = DigitalTwin(line, cfg).run(stream_events(str(events)))
        output["meta"]["cache_key"] = key
        twin_path.write_text(json.dumps(output, indent=1), encoding="utf-8", newline="\n")
        cached = output

    return ScenarioResult(scenario=scenario, ground_truth=ground_truth,
                          twin_output=cached, run_dir=run_dir)


def prepare_split(scenarios: Sequence[Scenario], cfg: TwinConfig,
                  line: LineConfig | None = None, out_root: Path = RUNS_ROOT,
                  horizon_s: float | None = None, force: bool = False,
                  verbose: bool = True) -> list[ScenarioResult]:
    """Prepare every scenario in a split."""
    line = line or load_line_config()
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        if verbose:
            print(f"  preparing {scenario.scenario_id} (seed {scenario.seed}) ...", flush=True)
        results.append(prepare_scenario(scenario, line, cfg, out_root, horizon_s, force))
    return results
