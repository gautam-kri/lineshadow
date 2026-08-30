"""The digital twin: consumes the event stream, maintains line state, runs L1-L3.

Reads exactly two things: the event stream (batch or streaming generator) and the
plant model in ``config/line.yaml``. It has no access to ``ground_truth.json``,
the counterfactual stream, or anything else the simulator knows. That separation
is enforced structurally by ``tests/test_isolation.py``, which runs this module in
a subprocess against a directory containing only ``events.jsonl``.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Iterator

from simulator.config import LineConfig

from .config import TwinConfig
from .l1_drift import L1Detector
from .l2_propagation import L2Propagator
from .l3_defect import L3DefectCorrelator
from .sparse import SparseInference
from .state import LineState, quantile

CHECKLIST_WINDOW = 10


class DigitalTwin:
    """Streaming twin of the assembly line."""

    def __init__(self, line: LineConfig, cfg: TwinConfig) -> None:
        self.line = line
        self.cfg = cfg
        self.state = LineState(line, cfg.l1, cfg.warmup, cfg.sparse)
        self.sparse = SparseInference(line, self.state, cfg.sparse)
        self.l1 = L1Detector(cfg, self.sparse)
        self.l2 = L2Propagator(line, self.state, cfg)
        self.l3 = L3DefectCorrelator(line, cfg)

        self.now = 0.0
        self.n_events = 0
        self.timeline: list[dict[str, Any]] = []
        self._next_tick: float | None = None
        self._tick_interval = float(cfg.l2["interval_s"])
        self._checklist_window: dict[int, deque[float]] = {
            sid: deque(maxlen=CHECKLIST_WINDOW) for sid in line.station_ids
        }
        self._min_direct_samples = int(cfg.warmup["min_samples"])
        self._min_transit_samples = int(cfg.sparse["min_transit_samples"])
        self._level_quantile = float(cfg.l1.get("low_quantile", 0.2))
        self._prime_units = int(cfg.warmup["line_prime_units"])
        self._prime_count = 0
        self._last_station = line.station_ids[-1]

    @property
    def primed(self) -> bool:
        """True once enough units have cleared the line that buffers are in steady state.

        Book-keeping (counts, open starts, pending transits) runs from the first
        event, but no detector baseline is fed until the line has filled -- the
        fill-up transient would otherwise anchor every baseline too low and make
        normal steady-state operation look like a universal upward drift.
        """
        return self._prime_count >= self._prime_units

    # --------------------------------------------------------------- ingest

    def observe(self, event: dict[str, Any]) -> None:
        """Consume one event from the stream."""
        ts = float(event["ts"])
        self.now = ts
        self.n_events += 1
        if self._next_tick is None:
            self._next_tick = ts + self._tick_interval

        kind = event["event"]
        if kind == "start":
            self._on_start(event, ts)
        elif kind == "finish":
            self._on_finish(event, ts)
        elif kind == "checklist":
            self._on_checklist(event, ts)
        elif kind == "inspection":
            self._on_inspection(event, ts)

        while self._next_tick is not None and ts >= self._next_tick:
            self._tick(self._next_tick)
            self._next_tick += self._tick_interval

    def _on_start(self, event: dict[str, Any], ts: float) -> None:
        sid = int(event["station"])
        st = self.state[sid]
        st.start_count += 1
        st.last_start_ts = ts
        st.open_starts[event["vin"]] = ts
        starved = st.last_finish_ts is None or ts > st.last_finish_ts + 1e-6
        for unknown_sid, attributed in self.sparse.on_start(sid, event["vin"], ts, starved):
            self._feed_inferred(unknown_sid, ts, attributed)

    def _on_finish(self, event: dict[str, Any], ts: float) -> None:
        sid = int(event["station"])
        st = self.state[sid]
        st.finish_count += 1
        st.last_finish_ts = ts
        if sid == self._last_station:
            self._prime_count += 1
        cycle_time = float(event["cycle_time"])

        started = st.open_starts.pop(event["vin"], None)
        if started is not None:
            blocked = max(0.0, ts - started - cycle_time)
            st.blocked_samples += 1
            st.blocked_ewma_s = 0.15 * blocked + 0.85 * st.blocked_ewma_s

        tracker = st.trackers.get("cycle_time")
        if tracker is not None and self.primed:
            conf = self._confidence(sid, tracker.n, self._min_direct_samples)
            self.l1.consider(tracker.update(ts, cycle_time, "direct", conf))
            self._update_direct_estimate(sid, tracker, conf)

        qt = st.trackers.get("torque")
        if qt is not None and self.primed and "quality_signal" in event:
            conf = self._confidence(sid, qt.n, self._min_direct_samples)
            reading = qt.update(ts, float(event["quality_signal"]), "direct", conf)
            self.l1.consider(reading)
            self.on_quality_sample(event["vin"], sid, float(event["quality_signal"]), qt, ts)

        self.sparse.on_finish(sid, event["vin"], ts)

    def _on_checklist(self, event: dict[str, Any], ts: float) -> None:
        sid = int(event["station"])
        st = self.state[sid]
        failed = 0.0 if bool(event["pass"]) else 1.0
        st.checklist_count += 1
        st.checklist_fail_count += int(failed)
        window = self._checklist_window[sid]
        window.append(failed)
        tracker = st.trackers.get("checklist")
        if tracker is not None and self.primed:
            rate = sum(window) / len(window)
            conf = self._confidence(sid, tracker.n, self._min_direct_samples)
            self.l1.consider(tracker.update(ts, rate, "inferred", conf))
            self.on_checklist_sample(event["vin"], sid, tracker, ts)

    def _on_inspection(self, event: dict[str, Any], ts: float) -> None:
        self.on_inspection_label(event["vin"], event["result"], event.get("defect_code"), ts)

    # ------------------------------------------------- hooks used by L3

    def on_quality_sample(self, vin: str, station: int, value: float,
                          tracker: Any, ts: float) -> None:
        """Feed a per-unit quality reading to L3."""
        reading = tracker.last_reading
        if reading is not None:
            self.l3.on_quality_sample(vin, station, reading.z, reading.ewma_stat, ts)

    def on_checklist_sample(self, vin: str, station: int, tracker: Any, ts: float) -> None:
        """Feed a sparse manual check to L3."""
        reading = tracker.last_reading
        if reading is not None:
            self.l3.on_checklist_sample(vin, station, reading.ewma_stat, ts)

    def on_inspection_label(self, vin: str, result: str, defect_code: Any, ts: float) -> None:
        """Feed a final-inspection outcome to L3, closing the calibration loop."""
        self.l3.on_inspection(vin, result, ts)

    # ------------------------------------------------------------ estimates

    @staticmethod
    def _spread(values: list[float]) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        return (var ** 0.5) / (n ** 0.5)

    def _confidence(self, station: int, n_samples: int, need: int) -> float:
        """Base confidence for the station, discounted while evidence is thin."""
        base = self.sparse.confidence_for(station)
        return base * min(1.0, n_samples / float(max(1, need)))

    def _update_direct_estimate(self, sid: int, tracker: Any, confidence: float) -> None:
        """Refresh the throughput-relevant estimate of this station's cycle time.

        The estimate is the *mean* of the recent window, because throughput is the
        reciprocal of the mean, and the band is the confidence interval on that
        mean. L2's p10/p50/p90 projections span the uncertainty in the estimate,
        not the spread of individual units: one slow car does not change a
        station's rate, and treating it as if it did makes L2 predict a
        bottleneck on every healthy station.
        """
        st = self.state[sid]
        values = list(tracker.recent)
        st.cycle_estimate_s = sum(values) / len(values) if values else st.nominal_cycle_s
        st.cycle_band_s = 1.96 * self._spread(values)
        st.cycle_p10_s = st.cycle_estimate_s - st.cycle_band_s
        st.cycle_p90_s = st.cycle_estimate_s + st.cycle_band_s
        st.estimate_basis = "direct"
        st.confidence = confidence

    def _feed_inferred(self, sid: int, ts: float, attributed: float) -> None:
        """One transit-derived cycle-time sample for an uninstrumented station.

        Samples reach here already filtered to units that entered a starved
        downstream anchor, which removes the anchor's queueing delay. What remains
        still carries a slow, line-wide congestion wander of a few tenths of a
        sigma. Rather than smooth it away -- smoothing makes the series strongly
        autocorrelated and its variance estimate unstable -- the detector gives
        this signal a wider CUSUM slack (``cusum_k_by_signal``), so benign wander
        is not integrated while a genuine multi-sigma shift still is.
        """
        st = self.state[sid]
        tracker = st.trackers.get("cycle_time_inferred")
        if tracker is None or not self.primed:
            return
        conf = self._confidence(sid, tracker.n, self._min_transit_samples)
        self.l1.consider(tracker.update(ts, attributed, "inferred", conf))

        if tracker.warm and tracker.recent and tracker.baseline_low_quantile is not None:
            # The *level* estimate uses a low quantile of the recent window rather
            # than its mean. A starve-filtered transit is still cycle time plus a
            # residual buffer wait, and that wait rises and falls with line-wide
            # congestion. The upper tail carries the congestion; the lower tail is
            # free-flow traversal, so a low quantile tracks the station's own
            # service time. Using the mean here makes a merely congested line look
            # like a slow station, and L2 then invents a bottleneck.
            offset = quantile(list(tracker.recent), self._level_quantile) - tracker.baseline_low_quantile
            st.cycle_estimate_s = st.nominal_cycle_s + offset
        else:
            st.cycle_estimate_s = st.nominal_cycle_s
        st.cycle_band_s = self.sparse.band_for(sid, 1.96 * self._spread(list(tracker.recent)))
        st.cycle_p10_s = st.cycle_estimate_s - st.cycle_band_s
        st.cycle_p90_s = st.cycle_estimate_s + st.cycle_band_s
        st.estimate_basis = "inferred"
        st.confidence = conf

    # ----------------------------------------------------------------- tick

    def _tick(self, ts: float) -> None:
        """Periodic work: refresh inferred buffer levels and snapshot the line."""
        self.state.refresh_buffers()
        self.on_tick(ts)
        self.timeline.append({
            "ts": round(ts, 1),
            "stations": [
                {
                    "station": sid,
                    "cycle_estimate_s": (
                        None if self.state[sid].cycle_estimate_s is None
                        else round(self.state[sid].cycle_estimate_s, 2)
                    ),
                    "buffer_pressure": round(self.state[sid].buffer_pressure, 3),
                    "confidence": round(self.state[sid].confidence, 3),
                    "basis": self.state[sid].estimate_basis,
                }
                for sid in self.line.station_ids
            ],
        })

    def on_tick(self, ts: float) -> None:
        """Project the line forward. Buffers were refreshed immediately before."""
        self.l2.project_now(ts)

    # --------------------------------------------------------------- output

    def run(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Consume a whole stream (list or generator) and return the twin output."""
        for event in events:
            self.observe(event)
        return self.output()

    def output(self) -> dict[str, Any]:
        """Everything the twin believes plus every candidate it raised."""
        self.state.refresh_buffers()
        return {
            "meta": {
                "n_events": self.n_events,
                "last_ts": round(self.now, 3),
                "n_stations": self.line.n_stations,
                "n_instrumented": len(self.line.instrumented_ids),
                "sensitivity": self.cfg.sensitivity,
                "l1_emission_floor": self.cfg.l1_emission_floor,
                "l2_emission_floor": self.cfg.l2_emission_floor,
                "l3_emission_floor": self.cfg.l3_emission_floor,
            },
            "l1_candidates": self.l1.candidates,
            "l2_candidates": self.l2.candidates,
            "l3_candidates": self.l3.candidates,
            "l3_summary": self.l3.summary(),
            "stations": self.state.snapshot(),
            "timeline": self.timeline,
        }


def stream_events(path: str) -> Iterator[dict[str, Any]]:
    """Yield events one at a time, so the twin can run without loading the file."""
    import json
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
