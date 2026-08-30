"""Threshold sweep: how precision, recall, lead time and false alarms trade off.

The twin runs once per scenario; each sensitivity point is a re-threshold of the
cached candidates. False alarms per shift come from the control scenarios only.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Sequence

from twin.config import TwinConfig
from twin.thresholds import select_all

from .harness import ScenarioResult
from .matching import EvalConfig
from .metrics import aggregate, score_scenario

SWEEP_COLUMNS = (
    "sensitivity",
    "l1_severity_threshold",
    "l2_confidence_threshold",
    "l3_risk_threshold",
    "precision",
    "recall",
    "n_detected",
    "n_faulted",
    "median_lead_time_min",
    "median_detection_vs_onset_min",
    "mean_containment_rate",
    "false_alarms_per_shift",
    "false_alarms_per_shift_low",
    "false_alarms_per_shift_high",
    "n_correct_station",
    "n_matched_in_window",
    "n_false_positives",
    "total_alerts",
)


def sensitivity_points(n: int) -> list[float]:
    """``n`` evenly spaced sensitivities on [0, 1], inclusive of both ends."""
    if n < 2:
        return [0.5]
    return [round(i / (n - 1), 6) for i in range(n)]


def sweep(results: Sequence[ScenarioResult], twin_cfg: TwinConfig,
          eval_cfg: EvalConfig) -> list[dict[str, Any]]:
    """Score every scenario at every sensitivity."""
    rows: list[dict[str, Any]] = []
    for s in sensitivity_points(eval_cfg.sweep_points):
        scores = [
            score_scenario(r.ground_truth, select_all(r.twin_output, twin_cfg, s), eval_cfg)
            for r in results
        ]
        agg = aggregate(scores, eval_cfg)
        fa = agg["false_alarms_per_shift"]
        rows.append({
            "sensitivity": s,
            "l1_severity_threshold": round(twin_cfg.l1_threshold(s), 4),
            "l2_confidence_threshold": round(twin_cfg.l2_threshold(s), 4),
            "l3_risk_threshold": round(twin_cfg.l3_threshold(s), 4),
            "precision": _r(agg["precision"], 4),
            "recall": _r(agg["recall"], 4),
            "n_detected": agg["n_detected"],
            "n_faulted": agg["n_faulted"],
            "median_lead_time_min": _r(agg["queue_forming"]["median_lead_time_min"]),
            "median_detection_vs_onset_min": _r(
                agg["non_queue_forming"]["median_detection_vs_onset_min"]),
            "mean_containment_rate": _r(agg["quality"]["mean_containment_rate"], 4),
            "false_alarms_per_shift": _r(fa["mean"], 3),
            "false_alarms_per_shift_low": _r(fa["low"], 3),
            "false_alarms_per_shift_high": _r(fa["high"], 3),
            "n_correct_station": agg["n_correct_station"],
            "n_matched_in_window": agg["n_matched_in_window"],
            "n_false_positives": agg["n_false_positives"],
            "total_alerts": sum(sc.n_alerts for sc in scores),
        })
    return rows


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def write_csv(rows: Sequence[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" stops Python translating the terminator, and an explicit LF
    # lineterminator stops csv writing CRLF -- so this file is LF on every
    # platform, like every other file the project writes.
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SWEEP_COLUMNS),
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_plot(rows: Sequence[dict[str, Any]], path: Path, title: str) -> Path:
    """Self-contained interactive plot. No image backend needed."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    x = [r["sensitivity"] for r in rows]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=x, y=[r["precision"] for r in rows],
                             name="precision", mode="lines+markers"), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=[r["recall"] for r in rows],
                             name="recall", mode="lines+markers"), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=[r["mean_containment_rate"] for r in rows],
                             name="containment (quality faults)", mode="lines+markers"),
                  secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=[r["false_alarms_per_shift"] for r in rows],
                             name="false alarms / shift", mode="lines+markers",
                             line={"dash": "dot"}), secondary_y=True)
    fig.add_trace(go.Scatter(x=x, y=[r["median_lead_time_min"] for r in rows],
                             name="median lead time (min)", mode="lines+markers",
                             line={"dash": "dash"}), secondary_y=True)
    fig.update_layout(title=title, xaxis_title="master sensitivity",
                      legend={"orientation": "h", "y": -0.2}, template="plotly_white")
    fig.update_yaxes(title_text="rate in [0,1]", secondary_y=False)
    fig.update_yaxes(title_text="alerts/shift  ·  minutes", secondary_y=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(path), include_plotlyjs="inline", full_html=True)
    return path
