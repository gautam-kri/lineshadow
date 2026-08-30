"""Fault models injected into the simulator.

Three families plus a ``none`` control. A fault is a pure function of the unit's
random draws, the station, the clock and how many units the target station has
processed since onset -- which is what keeps the counterfactual run aligned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rng import UnitDraws


class Fault:
    """Base fault: affects nothing. Used directly for ``none`` control scenarios."""

    family = "none"
    station: int | None = None
    onset_s: float | None = None

    def cycle_factor(self, station: int, now: float, n_since_onset: int, d: UnitDraws) -> float:
        """Multiplier applied to the station's base cycle time."""
        return 1.0

    def torque_shift_sd(self, station: int, now: float, n_since_onset: int) -> float:
        """Shift of the quality signal mean, in units of its healthy sd."""
        return 0.0

    def defect_probability(self, station: int, now: float, z: float) -> float:
        """Probability this unit picks up a fault-induced defect at ``station``."""
        return 0.0

    def describe(self) -> dict[str, Any]:
        return {"family": self.family}


@dataclass
class DriftFault(Fault):
    """A station's cycle-time or torque mean ramps by X% over N units from time T."""

    station: int
    onset_s: float
    signal: str = "cycle_time"  # "cycle_time" | "torque"
    shape: str = "linear"  # "linear" | "step"
    magnitude_pct: float = 20.0
    ramp_units: int = 120
    torque_shift_sigma: float = 2.5

    family = "drift"

    def _progress(self, now: float, n_since_onset: int) -> float:
        if now < self.onset_s:
            return 0.0
        if self.shape == "step":
            return 1.0
        if self.ramp_units <= 0:
            return 1.0
        return min(1.0, n_since_onset / float(self.ramp_units))

    def cycle_factor(self, station: int, now: float, n_since_onset: int, d: UnitDraws) -> float:
        if station != self.station or self.signal != "cycle_time":
            return 1.0
        return 1.0 + (self.magnitude_pct / 100.0) * self._progress(now, n_since_onset)

    def torque_shift_sd(self, station: int, now: float, n_since_onset: int) -> float:
        if station != self.station or self.signal != "torque":
            return 0.0
        return self.torque_shift_sigma * self._progress(now, n_since_onset)

    def describe(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "station": self.station,
            "onset_s": self.onset_s,
            "signal": self.signal,
            "shape": self.shape,
            "magnitude_pct": self.magnitude_pct,
            "ramp_units": self.ramp_units,
            "torque_shift_sigma": self.torque_shift_sigma,
        }


@dataclass
class SlowdownFault(Fault):
    """Intermittent stochastic slowdowns (occasional 2-3x cycle time) over a window."""

    station: int
    onset_s: float
    window_s: float = 14400.0
    probability: float = 0.18
    multiplier_min: float = 2.0
    multiplier_max: float = 3.0

    family = "slowdown"

    def cycle_factor(self, station: int, now: float, n_since_onset: int, d: UnitDraws) -> float:
        if station != self.station:
            return 1.0
        if not (self.onset_s <= now <= self.onset_s + self.window_s):
            return 1.0
        if float(d.slowdown_u[station]) >= self.probability:
            return 1.0
        span = self.multiplier_max - self.multiplier_min
        return self.multiplier_min + span * float(d.slowdown_mult_u[station])

    def describe(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "station": self.station,
            "onset_s": self.onset_s,
            "window_s": self.window_s,
            "probability": self.probability,
            "multiplier_min": self.multiplier_min,
            "multiplier_max": self.multiplier_max,
        }


@dataclass
class QualityFault(Fault):
    """A process shift at one station that only surfaces at final inspection.

    The shift is visible immediately in the station's quality signal -- that is
    what lets the unsupervised half of L3 act before any label exists -- but the
    resulting defect is not detected until station 40, many minutes downstream.
    That lag is the escape mechanism.
    """

    station: int
    onset_s: float
    fail_probability: float = 0.35
    torque_shift_sigma: float = 2.2
    defect_code: str = "TORQUE-LOW"
    base_rate: float = 0.005

    family = "quality"

    def torque_shift_sd(self, station: int, now: float, n_since_onset: int) -> float:
        if station != self.station or now < self.onset_s:
            return 0.0
        return self.torque_shift_sigma

    def defect_probability(self, station: int, now: float, z: float) -> float:
        if station != self.station or now < self.onset_s:
            return 0.0
        if self.torque_shift_sigma <= 0:
            return self.fail_probability
        # Failure risk scales with this unit's own deviation, so the observable
        # signal and the hidden outcome are genuinely correlated.
        p = self.fail_probability * max(0.0, z) / self.torque_shift_sigma
        return float(min(0.95, max(self.base_rate, p)))

    def describe(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "station": self.station,
            "onset_s": self.onset_s,
            "fail_probability": self.fail_probability,
            "torque_shift_sigma": self.torque_shift_sigma,
            "defect_code": self.defect_code,
        }


def build_fault(spec: dict[str, Any], base_defect_rate: float = 0.005) -> Fault:
    """Construct a fault object from a scenario file's ``fault:`` block."""
    family = str(spec.get("family", "none"))
    if family == "none":
        return Fault()
    if family == "drift":
        return DriftFault(
            station=int(spec["station"]),
            onset_s=float(spec["onset_s"]),
            signal=str(spec.get("signal", "cycle_time")),
            shape=str(spec.get("shape", "linear")),
            magnitude_pct=float(spec.get("magnitude_pct", 20.0)),
            ramp_units=int(spec.get("ramp_units", 120)),
            torque_shift_sigma=float(spec.get("torque_shift_sigma", 2.5)),
        )
    if family == "slowdown":
        return SlowdownFault(
            station=int(spec["station"]),
            onset_s=float(spec["onset_s"]),
            window_s=float(spec.get("window_s", 14400.0)),
            probability=float(spec.get("probability", 0.18)),
            multiplier_min=float(spec.get("multiplier_min", 2.0)),
            multiplier_max=float(spec.get("multiplier_max", 3.0)),
        )
    if family == "quality":
        return QualityFault(
            station=int(spec["station"]),
            onset_s=float(spec["onset_s"]),
            fail_probability=float(spec.get("fail_probability", 0.35)),
            torque_shift_sigma=float(spec.get("torque_shift_sigma", 2.2)),
            defect_code=str(spec.get("defect_code", "TORQUE-LOW")),
            base_rate=base_defect_rate,
        )
    raise ValueError(f"unknown fault family {family!r}")
