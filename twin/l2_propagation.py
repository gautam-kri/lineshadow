"""L2: forward projection of starve and block events.

This is a deterministic queueing propagation, not a nested simulation. Given the
current cycle-time estimates (drifted ones included) and inferred buffer levels,
the time to each downstream consequence is arithmetic:

* Station i is fed at ``f_i = min(demand, min upstream service rate)``. If its own
  service rate ``r_i`` is below ``f_i``, its input buffer fills at ``f_i - r_i``
  and saturates after ``(capacity - level) / (f_i - r_i)`` seconds. At that moment
  its *upstream* neighbour can no longer hand off work: a **block**.
* Once blocked, that neighbour's output drops to ``r_i``, so its own input buffer
  starts filling. The block walks upstream, one arithmetic step per station.
* Downstream of the constraint everything is fed at ``r_i``. Each buffer drains at
  ``min(service rates from the constraint to here) - r_i`` and empties after
  ``level / drain`` seconds, at which point that station **starves**.

A nested stochastic simulation every five minutes across a 15-hour run would
blow the runtime budget and add variance that cannot be debugged. For an
uncertainty band we instead run the same deterministic propagation three times,
at the 10th/50th/90th percentile cycle-time estimates, and let the agreement
between those three runs drive the prediction's confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from simulator.config import LineConfig

from .config import TwinConfig
from .sparse import confidence_label
from .state import LineState

PERCENTILE_KEYS = ("p10", "p50", "p90")


@dataclass(frozen=True)
class Prediction:
    """One projected starve or block event."""

    predicted_ts: float
    station: int
    kind: str  # "starve" | "block"
    cause_station: int
    time_to_event_s: float
    rate_deficit: float
    feed_rate: float
    service_rate: float
    buffer_level: float
    buffer_capacity: int

    @property
    def key(self) -> tuple[int, str]:
        return (self.station, self.kind)


def _cycle_times(state: LineState, ids: list[int], percentile: str) -> dict[int, float]:
    """Per-station cycle-time estimate at one percentile of its recent spread."""
    out: dict[int, float] = {}
    for sid in ids:
        st = state[sid]
        nominal = st.nominal_cycle_s
        # p10/p90 are the confidence bounds on the *estimate* of the mean cycle
        # time, not quantiles of individual units.
        if percentile == "p10":
            value = st.cycle_p10_s
        elif percentile == "p90":
            value = st.cycle_p90_s
        else:
            value = st.cycle_estimate_s
        out[sid] = max(1.0, float(value if value is not None else nominal))
    return out


def project(state: LineState, ids: list[int], cycle_times: dict[int, float],
            demand_rate: float, now: float, horizon_s: float,
            min_deficit: float, max_chain: int) -> dict[tuple[int, str], Prediction]:
    """Propagate the line forward deterministically and return predicted events."""
    rates = {sid: 1.0 / cycle_times[sid] for sid in ids}
    level = {sid: (state[sid].buffer_level if state[sid].buffer_level is not None
                   else state[sid].buffer_capacity * 0.5) for sid in ids}

    feed: dict[int, float] = {}
    running = demand_rate
    for sid in ids:
        feed[sid] = running
        running = min(running, rates[sid])

    predictions: dict[tuple[int, str], Prediction] = {}

    def record(p: Prediction) -> None:
        existing = predictions.get(p.key)
        if existing is None or p.predicted_ts < existing.predicted_ts:
            predictions[p.key] = p

    constraints = [sid for sid in ids if rates[sid] < feed[sid] - min_deficit]
    for c in constraints:
        r_c = rates[c]

        # --- block chain, walking upstream from the constraint ---------------
        elapsed = 0.0
        pos = ids.index(c)
        steps = 0
        while pos >= 0 and steps < max_chain:
            steps += 1
            sid = ids[pos]
            # Buffer `sid` fills at whatever its feed exceeds the constraint's rate:
            # for the constraint itself that is its own feed, and for an already
            # blocked upstream station it is that station's feed against the same
            # constraint rate, because the block has propagated back to it.
            deficit = feed[sid] - r_c
            if deficit <= min_deficit:
                break
            headroom = max(0.0, state[sid].buffer_capacity - level[sid])
            elapsed += headroom / deficit
            if elapsed > horizon_s:
                break
            upstream_pos = pos - 1
            if upstream_pos < 0:
                break
            record(Prediction(
                predicted_ts=now + elapsed, station=ids[upstream_pos], kind="block",
                cause_station=c, time_to_event_s=elapsed, rate_deficit=deficit,
                feed_rate=feed[sid], service_rate=r_c, buffer_level=level[sid],
                buffer_capacity=state[sid].buffer_capacity,
            ))
            pos = upstream_pos

        # --- starve chain, walking downstream from the constraint ------------
        elapsed = 0.0
        downstream_capability = float("inf")
        for sid in ids[ids.index(c) + 1: ids.index(c) + 1 + max_chain]:
            downstream_capability = min(downstream_capability, rates[sid])
            drain = downstream_capability - r_c
            if drain <= min_deficit:
                break
            elapsed += level[sid] / drain
            if elapsed > horizon_s:
                break
            record(Prediction(
                predicted_ts=now + elapsed, station=sid, kind="starve",
                cause_station=c, time_to_event_s=elapsed, rate_deficit=drain,
                feed_rate=r_c, service_rate=downstream_capability,
                buffer_level=level[sid], buffer_capacity=state[sid].buffer_capacity,
            ))
    return predictions


class L2Propagator:
    """Runs the three-percentile projection on a fixed cadence and scores agreement."""

    def __init__(self, line: LineConfig, state: LineState, cfg: TwinConfig) -> None:
        self.line = line
        self.state = state
        self.cfg = cfg
        self.horizon_s = float(cfg.l2["horizon_s"])
        self.min_deficit = float(cfg.l2["min_rate_deficit"])
        self.max_chain = int(cfg.l2["max_chain_stations"])
        self.floor = cfg.l2_emission_floor
        self.demand_rate = 1.0 / line.takt_time_s
        self.candidates: list[dict[str, Any]] = []
        self.latest: list[dict[str, Any]] = []

    def project_now(self, now: float) -> list[dict[str, Any]]:
        """Project the line forward and return this tick's predictions."""
        ids = self.line.station_ids
        runs: dict[str, dict[tuple[int, str], Prediction]] = {}
        for key in PERCENTILE_KEYS:
            runs[key] = project(
                self.state, ids, _cycle_times(self.state, ids, key),
                self.demand_rate, now, self.horizon_s, self.min_deficit, self.max_chain,
            )

        keys = sorted({k for run in runs.values() for k in run})
        emitted: list[dict[str, Any]] = []
        for key in keys:
            agreeing = [p for p in (runs[q].get(key) for q in PERCENTILE_KEYS) if p is not None]
            base = runs["p50"].get(key) or min(agreeing, key=lambda p: p.predicted_ts)
            agreement = len(agreeing) / len(PERCENTILE_KEYS)
            station_conf = self.state[base.station].confidence
            cause_conf = self.state[base.cause_station].confidence
            # min(), not the average: a prediction inherits the confidence of the
            # weakest link in its chain. An inferred cause therefore needs all
            # three percentile projections to agree before it can clear a mid
            # sensitivity threshold -- i.e. the rate deficit has to exceed the
            # inferred estimate's own (deliberately wide) uncertainty band.
            confidence = agreement * min(station_conf, cause_conf)
            if confidence < self.floor:
                continue

            times = {q: (runs[q][key].predicted_ts if key in runs[q] else None)
                     for q in PERCENTILE_KEYS}
            cause_state = self.state[base.cause_station]
            record = {
                "layer": "L2",
                "ts": round(now, 3),
                "predicted_ts": round(base.predicted_ts, 1),
                "station": base.station,
                "kind": base.kind,
                "cause_station": base.cause_station,
                "confidence": round(confidence, 4),
                "confidence_label": confidence_label(confidence),
                "basis": cause_state.estimate_basis,
                "evidence": {
                    "time_to_event_s": round(base.time_to_event_s, 1),
                    "time_to_event_min": round(base.time_to_event_s / 60.0, 1),
                    "cause_cycle_estimate_s": (
                        None if cause_state.cycle_estimate_s is None
                        else round(cause_state.cycle_estimate_s, 2)
                    ),
                    "cause_cycle_band_s": round(cause_state.cycle_band_s, 2),
                    "cause_nominal_cycle_s": round(cause_state.nominal_cycle_s, 2),
                    "cause_service_rate_per_s": round(base.service_rate, 6),
                    "feed_rate_per_s": round(base.feed_rate, 6),
                    "demand_rate_per_s": round(self.demand_rate, 6),
                    "rate_deficit_per_s": round(base.rate_deficit, 6),
                    "buffer_level_at_projection": round(base.buffer_level, 2),
                    "buffer_capacity": base.buffer_capacity,
                    "buffer_basis": self.state[base.station].buffer_basis,
                    "percentile_projections_agreeing": f"{len(agreeing)}/{len(PERCENTILE_KEYS)}",
                    "predicted_ts_by_percentile": {
                        q: (None if v is None else round(v, 1)) for q, v in times.items()
                    },
                    "estimate_basis": cause_state.estimate_basis,
                    "cause_confidence": round(cause_conf, 3),
                    "horizon_s": self.horizon_s,
                },
            }
            emitted.append(record)

        self.candidates.extend(emitted)
        self.latest = emitted
        return emitted


def summarise(predictions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compact roll-up of a prediction set, for the UI header."""
    rows = list(predictions)
    return {
        "n_predictions": len(rows),
        "n_block": sum(1 for r in rows if r["kind"] == "block"),
        "n_starve": sum(1 for r in rows if r["kind"] == "starve"),
        "cause_stations": sorted({r["cause_station"] for r in rows}),
        "earliest_predicted_ts": min((r["predicted_ts"] for r in rows), default=None),
    }
