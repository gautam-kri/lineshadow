"""Data access for the Streamlit app.

Every tab reads from here, so every tab is looking at the same live twin state.
Nothing is precomputed for display: the twin is run against the event stream and
the sensitivity slider re-thresholds those cached candidates, exactly as the
evaluation harness does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from eval.harness import prepare_scenario
from eval.matching import load_eval_config
from eval.metrics import aggregate, score_scenario
from simulator.config import (REPO_ROOT, Scenario, list_scenarios, load_line_config,
                              load_scenario)
from twin.config import config_hash, load_twin_config
from twin.thresholds import select_all, station_alerts

RUNS_ROOT = REPO_ROOT / "runs"
REPORTS = REPO_ROOT / "reports"
PERTURBATION_HORIZON_S = 28800.0  # 8 h: keeps the live panel under ~15 s
PERTURBATION_ONSET_S = 12600.0


@dataclass
class LoadedRun:
    """One scenario's stream, ground truth and twin output, ready for display."""

    scenario_id: str
    run_id: str
    run_dir: Path
    ground_truth: dict[str, Any]
    twin_output: dict[str, Any]
    split: str


@st.cache_resource
def get_line():
    return load_line_config()


@st.cache_resource
def get_eval_config():
    return load_eval_config()


def get_twin_config(sensitivity: float | None = None):
    """Twin config at a chosen sensitivity. Cheap enough to build per rerun."""
    return load_twin_config(sensitivity=sensitivity)


def available_scenarios() -> list[Scenario]:
    return list_scenarios("tuning") + list_scenarios("holdout")


@st.cache_data(show_spinner=False)
def _load(scenario_path: str, split: str, horizon_s: float | None,
          config_fingerprint: str) -> dict[str, Any]:
    """Simulate + run the twin (both cached on disk), returning plain dicts.

    ``config_fingerprint`` is not read; it is part of the cache key so that
    editing config/twin.yaml invalidates every cached view.
    """
    scenario = load_scenario(scenario_path)
    result = prepare_scenario(scenario, get_line(), get_twin_config(),
                              RUNS_ROOT, horizon_s=horizon_s)
    return {
        "scenario_id": scenario.scenario_id,
        "run_id": scenario.run_id,
        "run_dir": str(result.run_dir),
        "ground_truth": result.ground_truth,
        "twin_output": result.twin_output,
        "split": split,
    }


def load_run(scenario: Scenario, horizon_s: float | None = None) -> LoadedRun:
    """Load (simulating if necessary) one scenario's twin state."""
    path = REPO_ROOT / "config" / "scenarios" / scenario.split / f"{scenario.scenario_id}.yaml"
    raw = _load(str(path), scenario.split, horizon_s,
                config_hash(REPO_ROOT / "config" / "twin.yaml"))
    return LoadedRun(
        scenario_id=raw["scenario_id"], run_id=raw["run_id"],
        run_dir=Path(raw["run_dir"]), ground_truth=raw["ground_truth"],
        twin_output=raw["twin_output"], split=raw["split"],
    )


def alerts_for(run: LoadedRun, sensitivity: float) -> dict[str, list[dict[str, Any]]]:
    """Re-threshold the twin's cached candidates at the slider's sensitivity."""
    return select_all(run.twin_output, get_twin_config(), sensitivity)


def ranked_alerts(run: LoadedRun, sensitivity: float) -> list[dict[str, Any]]:
    return station_alerts(run.twin_output, get_twin_config(), sensitivity)


def grouped_alerts(run: LoadedRun, sensitivity: float) -> list[dict[str, Any]]:
    """Collapse repeat alerts into one operator-facing row per issue.

    A fault that is real and unaddressed keeps re-alerting for hours, which is
    correct detector behaviour and is what the evaluation scores. It is not a
    useful *feed*, so the console groups by (layer, station, signal) and shows
    when the issue was first raised, how many times it has re-fired since, and
    the evidence from its worst instance.
    """
    groups: dict[tuple[str, Any, Any], dict[str, Any]] = {}
    for alert in ranked_alerts(run, sensitivity):
        key = (alert["layer"], alert.get("station"),
               alert.get("signal") or alert.get("kind"))
        group = groups.get(key)
        if group is None:
            groups[key] = {**alert, "first_ts": alert["ts"], "last_ts": alert["ts"],
                           "repeat_count": 1, "peak_score": alert["rank_score"]}
            continue
        group["repeat_count"] += 1
        group["first_ts"] = min(group["first_ts"], alert["ts"])
        group["last_ts"] = max(group["last_ts"], alert["ts"])
        if alert["rank_score"] > group["peak_score"]:
            group.update({k: v for k, v in alert.items() if k != "ts"})
            group["peak_score"] = alert["rank_score"]
    rows = list(groups.values())
    rows.sort(key=lambda r: (-r["peak_score"], r["first_ts"]))
    return rows


def score(run: LoadedRun, sensitivity: float):
    """Score this run against its hidden ground truth (validation tab only)."""
    return score_scenario(run.ground_truth, alerts_for(run, sensitivity), get_eval_config())


# ------------------------------------------------------- false-alarm estimate


@st.cache_data(show_spinner=False)
def _control_candidates(split: str, config_fingerprint: str) -> list[dict[str, Any]]:
    """Cached twin candidates for every control scenario in a split."""
    out = []
    for sc in list_scenarios(split):
        if sc.family != "none":
            continue
        result = prepare_scenario(sc, get_line(), get_twin_config(), RUNS_ROOT)
        out.append({"scenario_id": sc.scenario_id,
                    "twin_output": result.twin_output,
                    "ground_truth": result.ground_truth})
    return out


def false_alarms_per_shift(sensitivity: float, split: str = "tuning") -> dict[str, Any]:
    """Live false-alarm estimate: control runs only, re-thresholded at ``sensitivity``.

    Measured on runs with no fault injected, where every alert is false by
    definition. Taking this from faulted runs would conflate a false alarm with a
    correct-but-mistimed one.
    """
    controls = _control_candidates(split, config_hash(REPO_ROOT / "config" / "twin.yaml"))
    if not controls:
        return {"mean": None, "n": 0, "low": None, "high": None}
    cfg = get_twin_config()
    ev = get_eval_config()
    scores = [score_scenario(c["ground_truth"], select_all(c["twin_output"], cfg, sensitivity), ev)
              for c in controls]
    result = aggregate(scores, ev)["false_alarms_per_shift"]
    result["split"] = split
    return result


# --------------------------------------------------------------- station view


def station_rows(run: LoadedRun, sensitivity: float) -> list[dict[str, Any]]:
    """Per-station display record: estimate, band, confidence, worst live alert."""
    line = get_line()
    alerts = alerts_for(run, sensitivity)
    worst: dict[int, float] = {}
    causes: dict[int, int] = {}
    for a in alerts["l1"]:
        worst[a["station"]] = max(worst.get(a["station"], 0.0), a["severity_score"])
    for a in alerts["l2"]:
        causes[a["cause_station"]] = causes.get(a["cause_station"], 0) + 1

    rows = []
    for snap in run.twin_output["stations"]:
        sid = snap["station"]
        st_cfg = line.station(sid)
        nominal = st_cfg.mean_cycle_s
        estimate = snap["cycle_estimate_s"] or nominal
        rows.append({
            **snap,
            "name": st_cfg.name,
            "zone": st_cfg.zone,
            "nominal_cycle_s": nominal,
            "deviation_pct": 100.0 * (estimate - nominal) / nominal,
            "severity": worst.get(sid, 0.0),
            "l2_cause_count": causes.get(sid, 0),
            "band_low": estimate - snap["cycle_band_s"],
            "band_high": estimate + snap["cycle_band_s"],
        })
    return rows


# ------------------------------------------------------------------ overrides


def overrides_path(run: LoadedRun) -> Path:
    return run.run_dir / "overrides.jsonl"


def log_override(run: LoadedRun, alert: dict[str, Any], action: str, note: str = "") -> None:
    """Append a supervisor decision. This is the only thing the UI ever writes."""
    record = {
        "logged_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "note": note,
        "alert": {
            "layer": alert["layer"],
            "ts": alert["ts"],
            "station": alert.get("station"),
            "signal": alert.get("signal") or alert.get("kind"),
            "cause_station": alert.get("cause_station"),
            "score": alert.get("severity_score", alert.get("confidence")),
            "confidence_label": alert.get("confidence_label"),
        },
    }
    path = overrides_path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record) + "\n")


def read_overrides(run: LoadedRun) -> list[dict[str, Any]]:
    path = overrides_path(run)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def override_rate(run: LoadedRun) -> dict[str, Any]:
    rows = read_overrides(run)
    accepted = sum(1 for r in rows if r["action"] == "accept")
    overridden = sum(1 for r in rows if r["action"] == "override")
    total = accepted + overridden
    return {"accepted": accepted, "overridden": overridden, "total": total,
            "override_rate": (overridden / total) if total else None}


# ----------------------------------------------------------------- perturbation


def run_perturbation(family: str, station: int, severity_pct: float, onset_s: float,
                     seed: int, horizon_s: float = PERTURBATION_HORIZON_S) -> dict[str, Any]:
    """Genuinely re-run simulate -> twin -> score for an ad-hoc fault.

    Nothing here is canned: the fault is injected into a fresh simulation, the
    counterfactual is run at the same seed, the twin sees only the event stream,
    and the result is scored with the same matching rule as the holdout report.
    """
    if family == "quality":
        fault = {"family": "quality", "station": station, "onset_s": onset_s,
                 "fail_probability": min(0.9, severity_pct / 100.0),
                 "torque_shift_sigma": 1.0 + severity_pct / 25.0,
                 "defect_code": "LIVE-PERTURBATION"}
    elif family == "slowdown":
        fault = {"family": "slowdown", "station": station, "onset_s": onset_s,
                 "window_s": horizon_s - onset_s,
                 "probability": min(0.6, severity_pct / 150.0),
                 "multiplier_min": 2.0, "multiplier_max": 3.0}
    else:
        fault = {"family": "drift", "station": station, "onset_s": onset_s,
                 "signal": "cycle_time", "shape": "linear",
                 "magnitude_pct": severity_pct, "ramp_units": 60}

    scenario = Scenario(
        scenario_id=f"live_{family}_s{station}", seed=seed, horizon_s=horizon_s,
        split="tuning", fault=fault,
        description=f"live perturbation panel: {family} at station {station}",
    )
    result = prepare_scenario(scenario, get_line(), get_twin_config(),
                              RUNS_ROOT / "_live", horizon_s=horizon_s, force=True)
    cfg = get_twin_config()
    alerts = select_all(result.twin_output, cfg)
    return {
        "scenario": scenario,
        "ground_truth": result.ground_truth,
        "twin_output": result.twin_output,
        "alerts": alerts,
        "score": score_scenario(result.ground_truth, alerts, get_eval_config()),
    }


def holdout_report_text() -> str | None:
    path = REPORTS / "holdout_report.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def sweep_rows() -> list[dict[str, Any]]:
    path = REPORTS / "holdout_results.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("sweep", [])
