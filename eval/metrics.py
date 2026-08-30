"""Scoring: lead time, containment, false alarms per shift.

Sign convention for lead time: **positive means early**.

Two reference points exist and they are never mixed into one aggregate:

``lead_time_queue_min``
    For faults that actually formed a queue: ``queue_formation_ts - first_correct_alert_ts``.
    Positive means the twin called it before the line backed up.

``detection_vs_onset_min``
    For faults that never formed a queue there is nothing to beat, so the only
    honest number is detection latency against onset: ``-(first_correct_alert_ts - onset_ts)``.
    It is negative whenever the alert follows onset, which it always does, since
    an alert before onset is scored as a false positive rather than an early win.

They are reported as separate columns everywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from twin.l3_defect import first_flag_by_vin

from .matching import (EvalConfig, classify, classify_for_precision,
                       first_correct_alert)


@dataclass
class ScenarioScore:
    """Everything measured for one scenario at one sensitivity."""

    scenario_id: str
    family: str
    target_station: int | None
    target_instrumented: bool | None
    queue_forming: bool
    n_alerts: int
    n_matched_in_window: int
    n_correct_station: int
    n_false_positives: int
    detected: bool
    first_alert_ts: float | None
    first_alert_layer: str | None
    first_alert_signal: str | None
    first_alert_confidence: float | None
    lead_time_queue_min: float | None
    detection_vs_onset_min: float | None
    containment_rate: float | None
    n_affected: int | None
    n_contained: int | None
    units_early_min: float | None
    throughput_loss_units: int
    horizon_s: float

    def as_row(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "target_station": self.target_station,
            "target_instrumented": self.target_instrumented,
            "queue_forming": self.queue_forming,
            "detected": self.detected,
            "lead_time_queue_min": _round(self.lead_time_queue_min),
            "detection_vs_onset_min": _round(self.detection_vs_onset_min),
            "first_alert_layer": self.first_alert_layer,
            "first_alert_signal": self.first_alert_signal,
            "first_alert_confidence": _round(self.first_alert_confidence, 3),
            "containment_rate": _round(self.containment_rate, 4),
            "n_affected": self.n_affected,
            "n_contained": self.n_contained,
            "units_early_min": _round(self.units_early_min),
            "n_alerts": self.n_alerts,
            "n_matched_in_window": self.n_matched_in_window,
            "n_correct_station": self.n_correct_station,
            "n_false_positives": self.n_false_positives,
            "throughput_loss_units": self.throughput_loss_units,
            "horizon_s": self.horizon_s,
        }


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _quality_metrics(alerts_l3: Iterable[dict[str, Any]],
                     ground_truth: dict[str, Any]) -> tuple[float | None, int, int, float | None]:
    """Containment rate and units-early for a quality fault.

    Containment is the share of affected units flagged *before their own*
    inspection timestamp -- the only definition under which a flag could actually
    have been acted on.
    """
    quality = ground_truth.get("quality")
    if not quality:
        return None, 0, 0, None
    affected = [a for a in quality["affected_vins"] if a["inspection_ts"] is not None]
    if not affected:
        return None, 0, 0, None

    first_flag = first_flag_by_vin(list(alerts_l3))
    contained = [a for a in affected
                 if a["vin"] in first_flag and first_flag[a["vin"]] < a["inspection_ts"]]
    earliest = min((first_flag[a["vin"]] for a in contained), default=None)
    first_inspection = quality["first_affected_inspection_ts"]
    units_early = None
    if earliest is not None and first_inspection is not None:
        units_early = (first_inspection - earliest) / 60.0
    return len(contained) / len(affected), len(affected), len(contained), units_early


def score_scenario(ground_truth: dict[str, Any], alerts: dict[str, list[dict[str, Any]]],
                   cfg: EvalConfig) -> ScenarioScore:
    """Score one scenario's alerts against its hidden ground truth."""
    station_alerts = list(alerts["l1"]) + list(alerts["l2"])
    matched, _ = classify(station_alerts, ground_truth, cfg)
    n_correct, n_false = classify_for_precision(station_alerts, ground_truth, cfg)
    first = first_correct_alert(station_alerts, ground_truth, cfg)

    lead_queue = None
    detect_onset = None
    if first is not None:
        if ground_truth["queue_forming"]:
            lead_queue = (ground_truth["queue_formation_ts"] - first["ts"]) / 60.0
        else:
            detect_onset = -(first["ts"] - ground_truth["onset_s"]) / 60.0

    containment, n_affected, n_contained, units_early = _quality_metrics(
        alerts["l3"], ground_truth)

    return ScenarioScore(
        scenario_id=ground_truth["scenario_id"],
        family=ground_truth["fault"]["family"],
        target_station=ground_truth["target_station"],
        target_instrumented=ground_truth["target_station_instrumented"],
        queue_forming=bool(ground_truth["queue_forming"]),
        n_alerts=len(station_alerts),
        n_matched_in_window=len(matched),
        n_correct_station=n_correct,
        n_false_positives=n_false,
        detected=first is not None,
        first_alert_ts=None if first is None else first["ts"],
        first_alert_layer=None if first is None else first["layer"],
        first_alert_signal=None if first is None else first.get("signal", first.get("kind")),
        first_alert_confidence=None if first is None else first.get("confidence"),
        lead_time_queue_min=lead_queue,
        detection_vs_onset_min=detect_onset,
        containment_rate=containment,
        n_affected=n_affected or None,
        n_contained=n_contained or None,
        units_early_min=units_early,
        throughput_loss_units=int(ground_truth["throughput_loss_units"]),
        horizon_s=float(ground_truth["horizon_s"]),
    )


# ------------------------------------------------------------------ aggregates


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else 0.5 * (s[mid - 1] + s[mid])


def mean_and_ci(values: Sequence[float], confidence: float = 0.95) -> dict[str, float | None]:
    """Mean with a Student-t interval. Small n is normal here, and is reported."""
    n = len(values)
    if n == 0:
        return {"mean": None, "low": None, "high": None, "n": 0, "sd": None}
    mean = sum(values) / n
    if n == 1:
        return {"mean": mean, "low": None, "high": None, "n": 1, "sd": None}
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(var)
    try:
        from scipy import stats
        t = float(stats.t.ppf(0.5 + confidence / 2.0, n - 1))
    except Exception:  # pragma: no cover - scipy is a pinned dependency
        t = 1.96
    half = t * sd / math.sqrt(n)
    # A rate cannot be negative; with the small n typical here the raw t-interval
    # can reach below zero, so the lower bound is clamped and the n is reported
    # alongside it so the reader can judge how much the interval is worth.
    return {"mean": mean, "low": max(0.0, mean - half), "high": mean + half,
            "n": n, "sd": sd}


def false_alarms_per_shift(control_scores: Sequence[ScenarioScore],
                           cfg: EvalConfig) -> dict[str, float | None]:
    """Measured on control scenarios only.

    On a faulted run you cannot cleanly separate a false alarm from a
    merely-mistimed true one, so the honest denominator is a line with no fault
    on it, where every alert is false by construction.
    """
    rates = [s.n_alerts / (s.horizon_s / cfg.shift_s) for s in control_scores]
    return mean_and_ci(rates, cfg.confidence_level)


def aggregate(scores: Sequence[ScenarioScore], cfg: EvalConfig) -> dict[str, Any]:
    """Roll scenario scores up into the headline numbers."""
    faulted = [s for s in scores if s.family != "none"]
    controls = [s for s in scores if s.family == "none"]
    queueing = [s for s in faulted if s.queue_forming]
    non_queueing = [s for s in faulted if not s.queue_forming]
    quality = [s for s in faulted if s.containment_rate is not None]

    correct = sum(s.n_correct_station for s in scores)
    false = sum(s.n_false_positives for s in scores)
    matched = sum(s.n_matched_in_window for s in scores)
    lead_values = [s.lead_time_queue_min for s in queueing if s.lead_time_queue_min is not None]
    onset_values = [s.detection_vs_onset_min for s in non_queueing
                    if s.detection_vs_onset_min is not None]

    return {
        "n_scenarios": len(scores),
        "n_faulted": len(faulted),
        "n_controls": len(controls),
        "n_detected": sum(1 for s in faulted if s.detected),
        "recall": (sum(1 for s in faulted if s.detected) / len(faulted)) if faulted else None,
        "precision": (correct / (correct + false)) if (correct + false) else None,
        "n_correct_station": correct,
        "n_matched_in_window": matched,
        "n_false_positives": false,
        "queue_forming": {
            "n": len(queueing),
            "n_detected": sum(1 for s in queueing if s.detected),
            "median_lead_time_min": median(lead_values),
            "min_lead_time_min": min(lead_values) if lead_values else None,
            "max_lead_time_min": max(lead_values) if lead_values else None,
        },
        "non_queue_forming": {
            "n": len(non_queueing),
            "n_detected": sum(1 for s in non_queueing if s.detected),
            "median_detection_vs_onset_min": median(onset_values),
        },
        "quality": {
            "n": len(quality),
            "mean_containment_rate": (
                sum(s.containment_rate for s in quality) / len(quality) if quality else None
            ),
            "total_affected": sum(s.n_affected or 0 for s in quality),
            "total_contained": sum(s.n_contained or 0 for s in quality),
            "median_units_early_min": median(
                [s.units_early_min for s in quality if s.units_early_min is not None]),
        },
        "false_alarms_per_shift": false_alarms_per_shift(controls, cfg),
        "throughput_loss_units_total": sum(s.throughput_loss_units for s in faulted),
    }
