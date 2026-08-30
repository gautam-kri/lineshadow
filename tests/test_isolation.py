"""Structural proof that the twin cannot read ground truth.

A grep for imports would not be enough -- it proves nothing about what the code
does at runtime. This runs the twin's real entrypoint in a *subprocess*, with its
working directory set to a temp folder that contains ``events.jsonl`` and nothing
else. ``ground_truth.json`` and ``counterfactual_events.jsonl`` are not merely
ignored, they do not exist. If the twin depended on either it would crash; if it
opportunistically read either it would behave differently when they were present,
which the last test here also rules out.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from simulator.runner import run_scenario


def _run_twin_subprocess(cwd, events_path, repo_root):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    return subprocess.run(
        [sys.executable, "-m", "twin", "--events", str(events_path), "--out", str(cwd)],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=600,
    )


def test_twin_runs_with_ground_truth_absent(tmp_path, line, drift_scenario, repo_root):
    art = run_scenario(drift_scenario, line, out_root=tmp_path / "sim")

    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "events.jsonl").write_bytes(art.events_path.read_bytes())

    assert not (sealed / "ground_truth.json").exists()
    assert not (sealed / "counterfactual_events.jsonl").exists()
    assert sorted(p.name for p in sealed.iterdir()) == ["events.jsonl"]

    proc = _run_twin_subprocess(sealed, sealed / "events.jsonl", repo_root)
    assert proc.returncode == 0, f"twin failed with ground truth absent:\n{proc.stderr}"

    output = json.loads((sealed / "twin_output.json").read_text(encoding="utf-8"))
    assert output["meta"]["n_events"] > 1000
    assert len(output["stations"]) == line.n_stations
    assert output["l1_candidates"], "twin produced no L1 candidates"
    assert output["timeline"], "twin produced no line-state timeline"
    assert sorted(p.name for p in sealed.iterdir()) == ["events.jsonl", "twin_output.json"]


def test_every_alert_carries_populated_evidence(tmp_path, line, drift_scenario, repo_root):
    art = run_scenario(drift_scenario, line, out_root=tmp_path / "sim")
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    (sealed / "events.jsonl").write_bytes(art.events_path.read_bytes())
    proc = _run_twin_subprocess(sealed, sealed / "events.jsonl", repo_root)
    assert proc.returncode == 0, proc.stderr

    output = json.loads((sealed / "twin_output.json").read_text(encoding="utf-8"))
    alerts = output["alerts_at_configured_sensitivity"]
    assert alerts["l1"], "no L1 alerts at the configured sensitivity"
    for layer in ("l1", "l2", "l3"):
        for alert in alerts[layer]:
            ev = alert.get("evidence")
            assert isinstance(ev, dict) and ev, f"{layer} alert without evidence: {alert}"
            assert any(isinstance(v, (int, float)) for v in ev.values()), \
                f"{layer} evidence carries no numbers: {ev}"
    for alert in alerts["l1"]:
        for key in ("baseline_mean", "baseline_sd", "current_value",
                    "cusum_stat", "sample_count", "estimate_basis"):
            assert key in alert["evidence"], f"L1 evidence missing {key}"


def test_presence_of_ground_truth_changes_nothing(tmp_path, line, drift_scenario, repo_root):
    """The twin's output must be byte-identical whether or not ground truth is on disk."""
    art = run_scenario(drift_scenario, line, out_root=tmp_path / "sim")

    outputs = []
    for name, with_truth in (("sealed", False), ("open", True)):
        d = tmp_path / name
        d.mkdir()
        (d / "events.jsonl").write_bytes(art.events_path.read_bytes())
        if with_truth:
            (d / "ground_truth.json").write_bytes(art.ground_truth_path.read_bytes())
            (d / "counterfactual_events.jsonl").write_bytes(art.counterfactual_path.read_bytes())
        proc = _run_twin_subprocess(d, d / "events.jsonl", repo_root)
        assert proc.returncode == 0, proc.stderr
        outputs.append((d / "twin_output.json").read_bytes())

    assert outputs[0] == outputs[1], "twin output changed when ground truth was present"
