"""L1: per-station drift detection by EWMA + CUSUM.

The detector emits a *continuous* ``severity_score`` and never thresholds. It
stores every reading at or above the sensitivity-1 emission floor, so
re-thresholding at any sensitivity is a filter over cached candidates rather than
a re-run -- which is what makes the threshold sweep cheap and its monotonicity
exact.

``evidence`` is mandatory and always carries the numbers behind the score.
"""

from __future__ import annotations

from typing import Any

from .config import TwinConfig
from .sparse import SparseInference, confidence_label
from .state import Reading

DIRECTION = {True: "above", False: "below"}


class L1Detector:
    """Turns detector readings into candidate drift alerts."""

    def __init__(self, cfg: TwinConfig, sparse: SparseInference) -> None:
        self.cfg = cfg
        self.sparse = sparse
        self.floor = cfg.l1_emission_floor
        self.candidates: list[dict[str, Any]] = []

    def consider(self, reading: Reading | None) -> dict[str, Any] | None:
        """Record a candidate if the reading clears the emission floor."""
        if reading is None or reading.severity < self.floor:
            return None
        evidence = reading.evidence()
        evidence.update(self.sparse.describe(reading.station))
        evidence["direction"] = DIRECTION[reading.ewma_stat >= 0]
        candidate = {
            "layer": "L1",
            "ts": round(reading.ts, 3),
            "station": reading.station,
            "signal": reading.signal,
            "severity_score": round(reading.severity, 4),
            "confidence": round(reading.confidence, 3),
            "confidence_label": confidence_label(reading.confidence),
            "basis": reading.basis,
            "evidence": evidence,
        }
        self.candidates.append(candidate)
        return candidate
