"""Per-station twin state: self-calibrating baselines, EWMA/CUSUM, buffer inference.

Nothing here reads ground truth. Every number is derived from the event stream
plus the plant model in ``config/line.yaml`` (topology, nominal cycle times,
buffer capacities, instrumentation coverage), which is engineering data an
operator would already have.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from simulator.config import LineConfig

RECENT_WINDOW = 60


def quantile(values: list[float], q: float) -> float:
    """Nearest-rank quantile of an unsorted list. Empty list returns 0.0."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


@dataclass
class Reading:
    """One detector reading for a (station, signal) pair."""

    ts: float
    station: int
    signal: str
    value: float
    z: float
    ewma_stat: float
    cusum_pos: float
    cusum_neg: float
    cusum_stat: float
    severity: float
    n_samples: int
    baseline_mean: float
    baseline_sd: float
    basis: str
    confidence: float
    autocorrelation: float = 0.0
    k_slack: float = 0.5
    h_decision: float = 5.0

    def evidence(self) -> dict[str, Any]:
        """The numbers behind the alert. Mandatory on every alert we emit."""
        return {
            "baseline_mean": round(self.baseline_mean, 4),
            "baseline_sd": round(self.baseline_sd, 4),
            "current_value": round(self.value, 4),
            "current_z": round(self.z, 3),
            "ewma_z": round(self.ewma_stat, 3),
            "cusum_pos": round(self.cusum_pos, 3),
            "cusum_neg": round(self.cusum_neg, 3),
            "cusum_stat": round(self.cusum_stat, 3),
            "sample_count": self.n_samples,
            "baseline_autocorrelation": round(self.autocorrelation, 3),
            "cusum_slack_k_sigma": round(self.k_slack, 3),
            "cusum_decision_h_sigma": round(self.h_decision, 3),
            "estimate_basis": self.basis,
            "estimate_confidence": round(self.confidence, 3),
        }


class SignalTracker:
    """EWMA + CUSUM on one signal at one station, self-calibrated on its own warm-up.

    The baseline mean and sd come from the first ``min_samples`` observations of
    this station's own history -- there is no global or cross-station prior, so a
    station with an unusual but stable process is not flagged for being unusual.
    """

    def __init__(self, station: int, signal: str, cfg: dict[str, Any],
                 warmup: dict[str, Any], sd_floor: float = 0.0) -> None:
        self.station = station
        self.signal = signal
        self.sd_floor = float(sd_floor)
        self.min_samples = int(warmup["min_samples"])
        self.baseline_window = int(warmup["baseline_window"])
        self.lam = float(cfg["ewma_lambda"])
        self.ewma_scale = float(cfg["ewma_scale"])
        self.k = float(cfg.get("cusum_k_by_signal", {}).get(signal, cfg["cusum_k_sigma"]))
        self.h = float(cfg["cusum_h_sigma"])
        self.cusum_cap = self.h * float(cfg["cusum_cap_multiple"])

        self._warm: list[float] = []
        self.autocorrelation = 0.0
        self.low_quantile = float(cfg.get("low_quantile", 0.2))
        self.baseline_low_quantile: float | None = None
        self.baseline_mean: float | None = None
        self.baseline_sd: float | None = None
        self.ewma_z = 0.0
        self.cusum_pos = 0.0
        self.cusum_neg = 0.0
        self.n = 0
        self.recent: deque[float] = deque(maxlen=RECENT_WINDOW)
        self.last_reading: Reading | None = None

    @property
    def warm(self) -> bool:
        return self.baseline_mean is not None

    @staticmethod
    def _lag1_autocorrelation(sample: list[float]) -> float:
        """Lag-1 autocorrelation, clipped to [0, 0.98]."""
        n = len(sample)
        if n < 8:
            return 0.0
        mean = sum(sample) / n
        num = sum((sample[i] - mean) * (sample[i - 1] - mean) for i in range(1, n))
        den = sum((x - mean) ** 2 for x in sample)
        if den <= 0:
            return 0.0
        return min(0.98, max(0.0, num / den))

    def _finalise_baseline(self) -> None:
        """Sample mean and long-run sd of this station's own warm-up window.

        Mean and sd, not median and MAD: mixed-model cycle times are a skewed
        mixture, and the median/MAD pair understates both the centre and the
        scale of such a mixture. That leaves z with a positive mean, which a CUSUM
        integrates into a guaranteed false alarm. The line fill-up transient --
        the reason robust statistics looked attractive -- is already excluded by
        the twin's prime guard, so the warm-up window is clean steady-state data.

        The sd is then inflated by the AR(1) long-run-variance factor
        sqrt((1+rho)/(1-rho)). That matters enormously for smoothed signals: a
        rolling transit quantile is strongly autocorrelated, so its marginal sd
        understates how far its *level* legitimately wanders. For a near-white
        signal such as a directly measured cycle time, rho ~ 0 and the factor is 1.
        """
        sample = self._warm[: self.baseline_window]
        n = len(sample)
        mean = sum(sample) / n
        var = sum((x - mean) ** 2 for x in sample) / max(1, n - 1)
        rho = self._lag1_autocorrelation(sample)
        self.autocorrelation = rho
        long_run = math.sqrt(var) * math.sqrt((1.0 + rho) / (1.0 - rho))
        self.baseline_mean = mean
        self.baseline_low_quantile = quantile(sample, self.low_quantile)
        # Guard against a degenerate baseline (e.g. a checklist that never failed
        # during warm-up), which would otherwise make every later z infinite.
        self.baseline_sd = max(long_run, abs(mean) * 0.01, self.sd_floor, 1e-3)

    def update(self, ts: float, value: float, basis: str = "direct",
               confidence: float = 1.0) -> Reading | None:
        """Feed one observation. Returns a Reading once the baseline is established."""
        self.n += 1
        self.recent.append(value)
        if not self.warm:
            self._warm.append(value)
            if len(self._warm) >= self.min_samples:
                self._finalise_baseline()
            return None

        assert self.baseline_mean is not None and self.baseline_sd is not None
        z = (value - self.baseline_mean) / self.baseline_sd
        self.ewma_z = self.lam * z + (1.0 - self.lam) * self.ewma_z
        # Rescale the EWMA to unit variance so `ewma_stat` reads in sd units.
        ewma_stat = self.ewma_z / math.sqrt(self.lam / (2.0 - self.lam))
        # Capped so a long-running fault saturates instead of growing without
        # bound, which keeps severity comparable across scenarios and runtimes.
        self.cusum_pos = min(self.cusum_cap, max(0.0, self.cusum_pos + z - self.k))
        self.cusum_neg = min(self.cusum_cap, max(0.0, self.cusum_neg - z - self.k))
        cusum_stat = max(self.cusum_pos, self.cusum_neg)

        severity = max(abs(ewma_stat) / self.ewma_scale, cusum_stat / self.h)
        reading = Reading(
            ts=ts, station=self.station, signal=self.signal, value=value, z=z,
            ewma_stat=ewma_stat, cusum_pos=self.cusum_pos, cusum_neg=self.cusum_neg,
            cusum_stat=cusum_stat, severity=severity, n_samples=self.n,
            baseline_mean=self.baseline_mean, baseline_sd=self.baseline_sd,
            basis=basis, confidence=confidence, autocorrelation=self.autocorrelation,
            k_slack=self.k, h_decision=self.h,
        )
        self.last_reading = reading
        return reading

@dataclass
class StationState:
    """Everything the twin currently believes about one station."""

    sid: int
    instrumented: bool
    nominal_cycle_s: float
    buffer_capacity: int
    trackers: dict[str, SignalTracker] = field(default_factory=dict)

    start_count: int = 0
    finish_count: int = 0
    last_start_ts: float | None = None
    last_finish_ts: float | None = None
    open_starts: dict[str, float] = field(default_factory=dict)

    cycle_estimate_s: float | None = None
    cycle_band_s: float = 0.0
    cycle_p10_s: float | None = None
    cycle_p90_s: float | None = None
    estimate_basis: str = "direct"
    confidence: float = 1.0

    blocked_ewma_s: float = 0.0
    blocked_samples: int = 0

    buffer_level: float | None = None
    buffer_level_low: float = 0.0
    buffer_level_high: float = 0.0
    buffer_basis: str = "exact"

    checklist_count: int = 0
    checklist_fail_count: int = 0

    @property
    def buffer_pressure(self) -> float:
        """Inferred input-buffer fill fraction in [0,1]; 0.0 when unknown."""
        if self.buffer_level is None or self.buffer_capacity <= 0:
            return 0.0
        return min(1.0, max(0.0, self.buffer_level / self.buffer_capacity))

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe view of current belief, for the UI and the run output."""
        return {
            "station": self.sid,
            "instrumented": self.instrumented,
            "cycle_estimate_s": None if self.cycle_estimate_s is None else round(self.cycle_estimate_s, 2),
            "cycle_band_s": round(self.cycle_band_s, 2),
            "estimate_basis": self.estimate_basis,
            "confidence": round(self.confidence, 3),
            "buffer_level": None if self.buffer_level is None else round(self.buffer_level, 2),
            "buffer_level_low": round(self.buffer_level_low, 2),
            "buffer_level_high": round(self.buffer_level_high, 2),
            "buffer_capacity": self.buffer_capacity,
            "buffer_basis": self.buffer_basis,
            "blocked_ewma_s": round(self.blocked_ewma_s, 2),
            "units_seen": max(self.finish_count, self.start_count),
            "checklist_fail_rate": (
                round(self.checklist_fail_count / self.checklist_count, 4)
                if self.checklist_count else None
            ),
        }


class LineState:
    """All station states plus the flow-conservation buffer inference."""

    def __init__(self, line: LineConfig, l1_cfg: dict[str, Any],
                 warmup: dict[str, Any], sparse_cfg: dict[str, Any]) -> None:
        self.line = line
        self.sparse_cfg = sparse_cfg
        self.stations: dict[int, StationState] = {}
        for sid in line.station_ids:
            st = line.station(sid)
            state = StationState(
                sid=sid, instrumented=st.instrumented,
                nominal_cycle_s=st.mean_cycle_s, buffer_capacity=st.buffer_capacity,
            )
            signals = ["cycle_time", "torque"] if st.instrumented else ["cycle_time_inferred", "checklist"]
            floors = l1_cfg.get("sd_floor", {})
            for sig in signals:
                if sig in l1_cfg["signals"]:
                    state.trackers[sig] = SignalTracker(
                        sid, sig, l1_cfg, warmup, sd_floor=float(floors.get(sig, 0.0)))
            state.cycle_estimate_s = st.mean_cycle_s
            state.buffer_level_high = float(st.buffer_capacity)
            self.stations[sid] = state
        self.now = 0.0

    def __getitem__(self, sid: int) -> StationState:
        return self.stations[sid]

    # ------------------------------------------------------------ buffers

    def _segment_bounds(self, buffer_id: int) -> tuple[int | None, int | None]:
        """Nearest instrumented station at or upstream of ``buffer_id-1``, and at or
        downstream of ``buffer_id``."""
        ids = self.line.station_ids
        upstream = None
        for sid in reversed([s for s in ids if s <= buffer_id - 1]):
            if self.stations[sid].instrumented:
                upstream = sid
                break
        downstream = None
        for sid in [s for s in ids if s >= buffer_id]:
            if self.stations[sid].instrumented:
                downstream = sid
                break
        return upstream, downstream

    def refresh_buffers(self) -> None:
        """Recompute every inferred buffer level from flow conservation.

        For a buffer with instrumented stations on both sides the level is exact:
        ``finish_count(i-1) - start_count(i)``. Otherwise the buffer sits inside a
        segment between the nearest instrumented stations; the segment's total WIP
        is exactly known, but its distribution across the segment's buffers and
        station slots is not, so we apportion by capacity and report the full
        feasible interval as the band.
        """
        for bid in self.line.station_ids:
            st = self.stations[bid]
            prev = bid - 1
            if prev >= self.line.station_ids[0] and self.stations[prev].instrumented and st.instrumented:
                level = self.stations[prev].finish_count - st.start_count
                st.buffer_level = float(max(0, min(st.buffer_capacity, level)))
                st.buffer_level_low = st.buffer_level
                st.buffer_level_high = st.buffer_level
                st.buffer_basis = "exact"
                continue

            a, d = self._segment_bounds(bid)
            if a is None or d is None:
                st.buffer_level = None
                st.buffer_level_low = 0.0
                st.buffer_level_high = float(st.buffer_capacity)
                st.buffer_basis = "unknown"
                continue

            seg_buffers = [b for b in self.line.station_ids if a < b <= d]
            seg_slots = sum(self.stations[b].buffer_capacity for b in seg_buffers) + (d - a - 1)
            wip = max(0, self.stations[a].finish_count - self.stations[d].start_count)
            wip = min(wip, seg_slots)
            share = st.buffer_capacity / seg_slots if seg_slots else 0.0
            st.buffer_level = round(wip * share, 3)
            st.buffer_level_low = float(max(0, wip - (seg_slots - st.buffer_capacity)))
            st.buffer_level_high = float(min(st.buffer_capacity, wip))
            st.buffer_basis = "inferred"

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.stations[sid].snapshot() for sid in self.line.station_ids]
