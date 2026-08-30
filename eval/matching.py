"""Deciding whether an alert actually caught the injected fault.

An alert counts as a true positive only if it names the faulted station or an
immediate neighbour *and* fires inside the scoring window. The window opens at
fault onset. An alert before onset is a false positive, not an early win -- that
rule is what stops a detector that alerts constantly from scoring perfect lead
time, and it is the single most important line in this file.

L1 alerts are matched on the station they name. L2 alerts are matched on
``cause_station``: an L2 prediction says "station X will starve *because of*
station Y", and Y is the diagnosis being scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from simulator.config import REPO_ROOT

DEFAULT_EVAL_CONFIG = REPO_ROOT / "config" / "eval.yaml"


@dataclass(frozen=True)
class EvalConfig:
    """The scoring protocol. Kept outside the frozen twin config on purpose."""

    station_tolerance: int
    match_margin_s: float
    onset_window_s: float
    shift_s: float
    sweep_points: int
    confidence_level: float

    @property
    def shift_hours(self) -> float:
        return self.shift_s / 3600.0


def load_eval_config(path: str | Path = DEFAULT_EVAL_CONFIG) -> EvalConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["eval"]
    return EvalConfig(
        station_tolerance=int(raw["station_tolerance"]),
        match_margin_s=float(raw["match_margin_s"]),
        onset_window_s=float(raw["onset_window_s"]),
        shift_s=float(raw["shift_s"]),
        sweep_points=int(raw["sweep_points"]),
        confidence_level=float(raw["confidence_level"]),
    )


def alert_station(alert: dict[str, Any]) -> int | None:
    """The station an alert is *about*: the cause for L2, the subject otherwise."""
    if alert.get("layer") == "L2":
        return alert.get("cause_station")
    return alert.get("station")


def scoring_window(ground_truth: dict[str, Any], cfg: EvalConfig) -> tuple[float, float] | None:
    """``(open, close)`` of the window in which an alert can be a true positive.

    Returns None for control scenarios, where there is no fault and therefore no
    window: every alert is false by definition.
    """
    if ground_truth["fault"]["family"] == "none":
        return None
    onset = ground_truth["onset_s"]
    if onset is None:
        return None
    if ground_truth["queue_forming"]:
        return onset, ground_truth["queue_formation_ts"] + cfg.match_margin_s
    return onset, onset + cfg.onset_window_s


def is_true_positive(alert: dict[str, Any], ground_truth: dict[str, Any],
                     cfg: EvalConfig) -> bool:
    """Correct station (within tolerance) and inside the scoring window."""
    window = scoring_window(ground_truth, cfg)
    if window is None:
        return False
    target = ground_truth["target_station"]
    station = alert_station(alert)
    if target is None or station is None:
        return False
    if abs(station - target) > cfg.station_tolerance:
        return False
    return window[0] <= alert["ts"] <= window[1]


def names_live_fault(alert: dict[str, Any], ground_truth: dict[str, Any],
                     cfg: EvalConfig) -> bool:
    """Correct station, raised at any point after onset while the fault is live.

    This is a *weaker* test than :func:`is_true_positive`, and the two exist for
    different questions. Lead time asks "did the twin call it before the line
    backed up?", so it uses the tight window. Precision asks "of the alerts an
    operator saw, how many pointed at something real?", and an alert naming the
    faulted station three hours after the queue formed still points at a genuine,
    still-unresolved fault -- counting it as a false positive would understate
    precision for the wrong reason. Alerts before onset remain false under both.
    """
    if ground_truth["fault"]["family"] == "none":
        return False
    onset = ground_truth["onset_s"]
    target = ground_truth["target_station"]
    station = alert_station(alert)
    if onset is None or target is None or station is None:
        return False
    return abs(station - target) <= cfg.station_tolerance and alert["ts"] >= onset


def classify(alerts: Iterable[dict[str, Any]], ground_truth: dict[str, Any],
             cfg: EvalConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split alerts into ``(matched, unmatched)`` under the strict lead-time rule."""
    tps: list[dict[str, Any]] = []
    fps: list[dict[str, Any]] = []
    for alert in alerts:
        (tps if is_true_positive(alert, ground_truth, cfg) else fps).append(alert)
    return tps, fps


def classify_for_precision(alerts: Iterable[dict[str, Any]], ground_truth: dict[str, Any],
                           cfg: EvalConfig) -> tuple[int, int]:
    """``(n_correct, n_false)`` under the live-fault rule used for precision."""
    rows = list(alerts)
    correct = sum(1 for a in rows if names_live_fault(a, ground_truth, cfg))
    return correct, len(rows) - correct


def first_correct_alert(alerts: Iterable[dict[str, Any]], ground_truth: dict[str, Any],
                        cfg: EvalConfig) -> dict[str, Any] | None:
    """Earliest true-positive alert, which is what lead time is measured from."""
    tps, _ = classify(alerts, ground_truth, cfg)
    return min(tps, key=lambda a: a["ts"]) if tps else None
