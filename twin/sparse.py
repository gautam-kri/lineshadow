"""Sparse-sensor inference for stations that emit nothing.

An uninstrumented station is invisible per-unit. What *is* visible is the time a
given VIN takes to travel from the last instrumented station upstream (``a``) to
the first instrumented station downstream (``d``): ``ts_start(d) - ts_finish(a)``.
That transit time is the sum of the intervening buffer waits, processing times
and blocked times, so a cycle-time change inside the segment moves it directly.

The estimator anchors each unknown station at its nominal cycle time from the
plant model and attributes the segment's *deviation from its own healthy
baseline* across the unknown stations in proportion to their nominal work
content. With one unknown station the whole deviation is attributed to it. With
several, the attribution is genuinely ambiguous, so the estimate is widened and
labelled ``low`` confidence -- the twin says "I cannot see this", never "green".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from simulator.config import LineConfig

from .state import LineState

CONFIDENCE_LABELS = ((0.8, "high"), (0.45, "medium"))


def confidence_label(score: float) -> str:
    """Map a confidence score to the label the UI renders."""
    for cut, name in CONFIDENCE_LABELS:
        if score >= cut:
            return name
    return "low"


@dataclass
class Segment:
    """A maximal run of uninstrumented stations bracketed by instrumented ones."""

    upstream: int
    downstream: int
    unknown: list[int]
    nominal: dict[int, float]
    shares: dict[int, float]
    nominal_transit_s: float
    pending: dict[str, float] = field(default_factory=dict)
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    n_offered: int = 0
    n_rejected: int = 0

    @property
    def n_unknown(self) -> int:
        return len(self.unknown)


def build_segments(line: LineConfig) -> list[Segment]:
    """Group the uninstrumented stations into bracketed segments."""
    ids = line.station_ids
    segments: list[Segment] = []
    run: list[int] = []
    for sid in ids:
        if not line.station(sid).instrumented:
            run.append(sid)
            continue
        if run:
            segments.append(_make_segment(line, run, sid))
            run = []
    if run:  # trailing uninstrumented tail with no downstream anchor
        segments.append(_make_segment(line, run, None))
    return segments


def _make_segment(line: LineConfig, run: list[int], downstream: int | None) -> Segment:
    ids = line.station_ids
    first = run[0]
    upstream = None
    for sid in reversed([s for s in ids if s < first]):
        if line.station(sid).instrumented:
            upstream = sid
            break
    nominal = {u: line.station(u).mean_cycle_s for u in run}
    total = sum(nominal.values()) or 1.0
    return Segment(
        upstream=upstream if upstream is not None else -1,
        downstream=downstream if downstream is not None else -1,
        unknown=list(run),
        nominal=nominal,
        shares={u: nominal[u] / total for u in run},
        nominal_transit_s=total,
    )


class SparseInference:
    """Derives cycle-time estimates and uncertainty bands for unseen stations."""

    def __init__(self, line: LineConfig, state: LineState, cfg: dict[str, Any]) -> None:
        self.line = line
        self.state = state
        self.cfg = cfg
        self.segments = [s for s in build_segments(line) if s.upstream > 0 and s.downstream > 0]
        self._by_upstream: dict[int, list[Segment]] = {}
        self._by_downstream: dict[int, list[Segment]] = {}
        for seg in self.segments:
            self._by_upstream.setdefault(seg.upstream, []).append(seg)
            self._by_downstream.setdefault(seg.downstream, []).append(seg)
        self.inflation = float(cfg["uncertainty_inflation"])
        self.multi_inflation = float(cfg["multi_unknown_extra_inflation"])

    # ---------------------------------------------------------------- inputs

    def on_finish(self, station: int, vin: str, ts: float) -> None:
        """A unit departed an instrumented station: open a transit measurement."""
        for seg in self._by_upstream.get(station, ()):
            seg.pending[vin] = ts

    def on_start(self, station: int, vin: str, ts: float,
                 downstream_starved: bool) -> list[tuple[int, float]]:
        """A unit entered an instrumented station: close any open transit measurement.

        Only units that entered a *starved* downstream anchor yield a sample. If
        the anchor was busy, the unit queued in the anchor's input buffer and the
        transit time carries that queueing delay -- a line-wide congestion term
        that has nothing to do with the unknown station. Requiring the anchor to
        have been idle and waiting removes that term, leaving a transit that is
        dominated by the segment's own service time.

        Returns ``(station_id, attributed_cycle_time_s)`` samples for the unknown
        stations in the segment just traversed.
        """
        out: list[tuple[int, float]] = []
        for seg in self._by_downstream.get(station, ()):
            opened = seg.pending.pop(vin, None)
            if opened is None:
                continue
            transit = ts - opened
            if transit <= 0:
                continue
            seg.n_offered += 1
            if not downstream_starved:
                seg.n_rejected += 1
                continue
            seg.samples.append(transit)
            excess = transit - seg.nominal_transit_s
            for u in seg.unknown:
                out.append((u, seg.nominal[u] + excess * seg.shares[u]))
        return out

    # --------------------------------------------------------------- outputs

    def confidence_for(self, station: int) -> float:
        """Confidence in this station's estimate, before any sample-count discount."""
        if self.line.station(station).instrumented:
            return float(self.cfg["confidence_direct"])
        for seg in self.segments:
            if station in seg.unknown:
                return float(
                    self.cfg["confidence_inferred_single"] if seg.n_unknown == 1
                    else self.cfg["confidence_inferred_multi"]
                )
        return float(self.cfg["confidence_inferred_multi"])

    def segment_for(self, station: int) -> Segment | None:
        for seg in self.segments:
            if station in seg.unknown:
                return seg
        return None

    def band_for(self, station: int, direct_band_s: float) -> float:
        """Uncertainty half-width for an inferred estimate.

        Always strictly wider than the equivalent direct measurement: the segment
        transit carries the variance of several stations plus buffer waits, and we
        additionally inflate, twice over when several stations are indistinguishable.
        """
        seg = self.segment_for(station)
        if seg is None:
            return direct_band_s
        n = len(seg.samples)
        if n >= 2:
            mean = sum(seg.samples) / n
            var = sum((x - mean) ** 2 for x in seg.samples) / (n - 1)
            spread = (var ** 0.5) * seg.shares[station] / max(1.0, n ** 0.5)
        else:
            spread = seg.nominal[station] * 0.25
        band = max(spread, direct_band_s) * self.inflation
        if seg.n_unknown > 1:
            band *= self.multi_inflation
        return band

    def describe(self, station: int) -> dict[str, Any]:
        """Evidence describing how a station's estimate was obtained."""
        st = self.line.station(station)
        if st.instrumented:
            return {"observability": "instrumented", "estimate_basis": "direct"}
        seg = self.segment_for(station)
        if seg is None:
            return {"observability": "uninstrumented", "estimate_basis": "inferred",
                    "note": "no instrumented anchor on both sides; estimate is nominal only"}
        return {
            "observability": "uninstrumented",
            "estimate_basis": "inferred",
            "anchor_upstream_station": seg.upstream,
            "anchor_downstream_station": seg.downstream,
            "unknown_stations_in_segment": seg.unknown,
            "attribution_share": round(seg.shares[station], 3),
            "transit_samples": len(seg.samples),
            "transit_samples_used": seg.n_offered - seg.n_rejected,
            "transit_samples_rejected_busy_anchor": seg.n_rejected,
            "nominal_transit_s": round(seg.nominal_transit_s, 2),
        }
