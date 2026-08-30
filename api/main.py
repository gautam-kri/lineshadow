"""Thin JSON wrapper around the Ninja engine.

Presentation layer only. Every endpoint here delegates to functions that already
exist in ``simulator/``, ``twin/`` and ``eval/`` -- none of them reimplement any
logic, and nothing in this module is allowed to change engine behaviour. If the
frontend needs something the engine does not expose, the fix is a read-only
accessor in the engine, not a reimplementation here.

    pip install -r api/requirements.txt
    uvicorn api.main:app --reload --port 8000

The heavy work (simulate -> counterfactual -> twin) is cached on disk by
``eval.harness.prepare_scenario``, so the first request for a scenario takes a
few seconds and subsequent ones are immediate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from eval.harness import prepare_scenario  # noqa: E402
from eval.matching import load_eval_config  # noqa: E402
from eval.metrics import score_scenario  # noqa: E402
from simulator.config import Scenario, list_scenarios, load_line_config, load_scenario  # noqa: E402
from twin.config import load_twin_config  # noqa: E402
from twin.thresholds import select_all, station_alerts  # noqa: E402

RUNS_ROOT = REPO_ROOT / "runs"
REPORTS = REPO_ROOT / "reports"

# Matches the Streamlit console's live panel: short enough to feel interactive.
PERTURBATION_HORIZON_S = 28800.0

app = FastAPI(
    title="Ninja engine API",
    description="Read-only JSON access to the simulator, twin and eval harness.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_line = load_line_config()
_eval_cfg = load_eval_config()


def _twin_cfg(sensitivity: float | None = None):
    return load_twin_config(sensitivity=sensitivity)


# ------------------------------------------------------------------ models

class PerturbationRequest(BaseModel):
    """An ad-hoc fault to inject into a fresh simulation."""

    family: Literal["drift", "slowdown", "quality"] = "drift"
    station: int = Field(ge=1, description="target station id")
    severity_pct: float = Field(default=30.0, ge=1.0, le=90.0)
    onset_s: float = Field(default=12600.0, ge=0.0)
    seed: int = Field(default=1777, ge=1000, le=1999,
                      description="tuning-range seed; holdout seeds are refused")


# ------------------------------------------------------------------ routes

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "stations": _line.n_stations,
            "instrumented": len(_line.instrumented_ids)}


@app.get("/api/line")
def line() -> dict[str, Any]:
    """Static plant model: topology, instrumentation coverage, buffer sizes.

    This is engineering data an operator would already have, and it is what the
    frontend draws the 40-station diagram from.
    """
    return {
        "n_stations": _line.n_stations,
        "takt_time_s": _line.takt_time_s,
        "inspection_station": _line.inspection_station,
        "zones": {k: list(v) for k, v in _line.zones.items()},
        "instrumented_ids": _line.instrumented_ids,
        "uninstrumented_ids": _line.uninstrumented_ids,
        "stations": [
            {
                "id": s.id, "name": s.name, "zone": s.zone,
                "nominal_cycle_s": s.mean_cycle_s,
                "buffer_capacity": s.buffer_capacity,
                "instrumented": s.instrumented,
            }
            for s in (_line.station(i) for i in _line.station_ids)
        ],
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict[str, Any]]:
    out = []
    for split in ("tuning", "holdout"):
        for sc in list_scenarios(split):
            out.append({
                "scenario_id": sc.scenario_id, "split": sc.split, "seed": sc.seed,
                "horizon_s": sc.horizon_s, "family": sc.family,
                "target_station": sc.target_station, "description": sc.description,
            })
    return out


def _run_payload(result, cfg, sensitivity: float) -> dict[str, Any]:
    alerts = select_all(result.twin_output, cfg, sensitivity)
    score = score_scenario(result.ground_truth, alerts, _eval_cfg)
    return {
        "scenario_id": result.scenario.scenario_id,
        "split": result.scenario.split,
        "sensitivity": sensitivity,
        "thresholds": {
            "l1": cfg.l1_threshold(sensitivity),
            "l2": cfg.l2_threshold(sensitivity),
            "l3": cfg.l3_threshold(sensitivity),
        },
        "stations": result.twin_output["stations"],
        "timeline": result.twin_output["timeline"],
        "l3_summary": result.twin_output["l3_summary"],
        "alerts": alerts,
        "ranked_alerts": station_alerts(result.twin_output, cfg, sensitivity),
        "ground_truth": result.ground_truth,
        "score": score.as_row(),
    }


@app.get("/api/run/{scenario_id}")
def run(scenario_id: str, sensitivity: float = 0.5) -> dict[str, Any]:
    """Twin state and alerts for one scenario, re-thresholded at ``sensitivity``.

    Re-thresholding is a filter over cached candidates, so changing sensitivity
    never re-runs the twin.
    """
    if not 0.0 <= sensitivity <= 1.0:
        raise HTTPException(422, "sensitivity must be in [0, 1]")
    match = next((sc for split in ("tuning", "holdout")
                  for sc in list_scenarios(split) if sc.scenario_id == scenario_id), None)
    if match is None:
        raise HTTPException(404, f"unknown scenario {scenario_id!r}")

    cfg = _twin_cfg()
    result = prepare_scenario(match, _line, cfg, RUNS_ROOT)
    return _run_payload(result, cfg, sensitivity)


@app.get("/api/holdout")
def holdout() -> dict[str, Any]:
    """The sealed holdout bundle: per-scenario rows, summary and threshold sweep.

    Served from ``reports/holdout_results.json`` rather than re-scored on demand,
    because that file is the artefact the report and README quote from -- serving
    anything else here would let the site drift away from the published numbers.
    """
    path = REPORTS / "holdout_results.json"
    if not path.exists():
        raise HTTPException(
            503, "holdout results not generated; run `python -m eval.run_holdout`")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/perturb")
def perturb(req: PerturbationRequest) -> dict[str, Any]:
    """Inject a fault into a fresh simulation and score the result.

    Genuinely re-runs simulate -> same-seed counterfactual -> twin -> score. The
    seed is constrained to the tuning range so this endpoint can never be used to
    manufacture a holdout result.
    """
    if req.station not in _line.station_ids:
        raise HTTPException(422, f"station {req.station} is not on this line")

    if req.family == "quality":
        fault: dict[str, Any] = {
            "family": "quality", "station": req.station, "onset_s": req.onset_s,
            "fail_probability": min(0.9, req.severity_pct / 100.0),
            "torque_shift_sigma": 1.0 + req.severity_pct / 25.0,
            "defect_code": "LIVE-PERTURBATION",
        }
    elif req.family == "slowdown":
        fault = {
            "family": "slowdown", "station": req.station, "onset_s": req.onset_s,
            "window_s": max(0.0, PERTURBATION_HORIZON_S - req.onset_s),
            "probability": min(0.6, req.severity_pct / 150.0),
            "multiplier_min": 2.0, "multiplier_max": 3.0,
        }
    else:
        fault = {
            "family": "drift", "station": req.station, "onset_s": req.onset_s,
            "signal": "cycle_time", "shape": "linear",
            "magnitude_pct": req.severity_pct, "ramp_units": 60,
        }

    scenario = Scenario(
        scenario_id=f"live_{req.family}_s{req.station}", seed=req.seed,
        horizon_s=PERTURBATION_HORIZON_S, split="tuning", fault=fault,
        description="live perturbation panel",
    )
    cfg = _twin_cfg()
    result = prepare_scenario(scenario, _line, cfg, RUNS_ROOT / "_live",
                              horizon_s=PERTURBATION_HORIZON_S, force=True)
    payload = _run_payload(result, cfg, cfg.sensitivity)
    payload["horizon_s"] = PERTURBATION_HORIZON_S
    payload["station_instrumented"] = _line.station(req.station).instrumented
    return payload
