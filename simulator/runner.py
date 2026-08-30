"""Scenario runner: faulted pass + counterfactual pass + ground truth on disk.

Writes ``runs/<run_id>/``::

    events.jsonl                 the only file the twin is ever allowed to read
    ground_truth.json            hidden; eval/ only
    counterfactual_events.jsonl  kept for audit; never read by the twin
    scenario.json                the resolved scenario, for reproducibility
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, LineConfig, Scenario, load_line_config
from .engine import RunResult, simulate
from .faults import Fault, build_fault
from .ground_truth import build_ground_truth

RUNS_ROOT = REPO_ROOT / "runs"


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records one per line with LF endings, for byte-stable output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")))
            fh.write("\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts."""
    out: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@dataclass
class RunArtifacts:
    """Where a completed scenario run put its files, plus the in-memory results."""

    run_id: str
    run_dir: Path
    events_path: Path
    ground_truth_path: Path
    counterfactual_path: Path
    ground_truth: dict[str, Any]
    faulted: RunResult
    counterfactual: RunResult


def run_scenario(
    scenario: Scenario,
    line: LineConfig | None = None,
    out_root: Path | str = RUNS_ROOT,
    horizon_s: float | None = None,
    write_counterfactual: bool = True,
) -> RunArtifacts:
    """Simulate one scenario twice (faulted + counterfactual) and persist everything."""
    line = line or load_line_config()
    horizon = float(horizon_s) if horizon_s is not None else scenario.horizon_s
    fault: Fault = build_fault(scenario.fault, base_defect_rate=line.base_defect_rate)

    faulted = simulate(line, fault, scenario.seed, horizon)
    counterfactual = simulate(line, Fault(), scenario.seed, horizon)
    gt = build_ground_truth(scenario, fault, faulted, counterfactual, line)

    run_dir = Path(out_root) / scenario.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    gt_path = run_dir / "ground_truth.json"
    cf_path = run_dir / "counterfactual_events.jsonl"

    write_jsonl(events_path, faulted.events)
    if write_counterfactual:
        write_jsonl(cf_path, counterfactual.events)
    gt_path.write_text(json.dumps(gt, indent=2), encoding="utf-8", newline="\n")
    (run_dir / "scenario.json").write_text(
        json.dumps(
            {
                "scenario_id": scenario.scenario_id,
                "split": scenario.split,
                "seed": scenario.seed,
                "horizon_s": horizon,
                "fault": scenario.fault,
                "description": scenario.description,
            },
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return RunArtifacts(
        run_id=scenario.run_id,
        run_dir=run_dir,
        events_path=events_path,
        ground_truth_path=gt_path,
        counterfactual_path=cf_path,
        ground_truth=gt,
        faulted=faulted,
        counterfactual=counterfactual,
    )
