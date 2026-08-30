"""SimPy model of a ~40-station mixed-model vehicle assembly line.

Topology
--------
Stations 1..N in series. ``buffer[i]`` is the *input* buffer of station i and is
fed by station i-1; buffer 1 is fed by the part-arrival process. A station pulls
one unit, processes it, then pushes it downstream -- blocking if the downstream
buffer is full, starving if its own input buffer is empty.

Observability
-------------
Instrumented stations emit ``start``/``finish`` per unit. ``start`` is when
processing begins and ``finish`` is when the unit *departs* the station, so
``ts_finish - ts_start - cycle_time`` is the blocked time and
``count(finish@i-1) - count(start@i)`` is the exact level of buffer i. Both are
recoverable by the twin from the stream alone.

Uninstrumented stations emit nothing per unit, only a sparse manual checklist.
Buffer levels are never emitted, by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import simpy

from .config import LineConfig
from .faults import Fault
from .rng import UnitDraws, draws_for_unit

TS_DECIMALS = 3


@dataclass
class Unit:
    """One vehicle moving down the line."""

    index: int
    vin: str
    model: str
    draws: UnitDraws
    released_ts: float = 0.0
    build_ts: dict[int, float] = field(default_factory=dict)
    torque: dict[int, float] = field(default_factory=dict)
    base_defect: bool = False
    fault_defect: bool = False
    defect_code: str | None = None
    defect_station: int | None = None
    inspection_ts: float | None = None
    inspection_result: str | None = None


class _MonitoredStore(simpy.Store):
    """A Store that reports its level to the engine on every successful put/get."""

    def __init__(self, env: simpy.Environment, capacity: int, bid: int,
                 on_put: Callable[[int, float, Unit, int], None]) -> None:
        super().__init__(env, capacity)
        self.bid = bid
        self._on_put = on_put

    def _do_put(self, event: Any) -> None:  # type: ignore[override]
        super()._do_put(event)
        if event.triggered:
            self._on_put(self.bid, self._env.now, event.item, len(self.items))


@dataclass
class RunResult:
    """Everything one simulation pass produced."""

    events: list[dict[str, Any]]
    saturation: dict[tuple[int, int], float]
    puts: dict[int, list[tuple[int, float, bool]]]
    units: list[Unit]
    horizon_s: float
    n_released: int
    n_completed: int

    def saturation_keys(self) -> set[tuple[int, int]]:
        return set(self.saturation)


class LineSimulation:
    """A single simulation pass: either the faulted run or its counterfactual."""

    def __init__(self, line: LineConfig, fault: Fault, seed: int, horizon_s: float) -> None:
        self.line = line
        self.fault = fault
        self.seed = int(seed)
        self.horizon_s = float(horizon_s)

        self.env = simpy.Environment()
        self.buffers: dict[int, _MonitoredStore] = {
            sid: _MonitoredStore(self.env, line.station(sid).buffer_capacity, sid, self._on_put)
            for sid in line.station_ids
        }
        self.events: list[dict[str, Any]] = []
        self.saturation: dict[tuple[int, int], float] = {}
        self.puts: dict[int, list[tuple[int, float, bool]]] = {sid: [] for sid in line.station_ids}
        self.units: list[Unit] = []
        self._completed: list[Unit] = []
        self._seq = 0
        self._fault_count = 0
        self._station_counts: dict[int, int] = {sid: 0 for sid in line.station_ids}
        self._model_cdf = self._build_model_cdf(line.models)

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _build_model_cdf(models: dict[str, float]) -> list[tuple[float, str]]:
        total = sum(models.values())
        cdf: list[tuple[float, str]] = []
        acc = 0.0
        for name in sorted(models):
            acc += models[name] / total
            cdf.append((acc, name))
        return cdf

    def _model_for(self, u: float) -> str:
        for edge, name in self._model_cdf:
            if u <= edge:
                return name
        return self._model_cdf[-1][1]

    # ------------------------------------------------------------- recording

    def _emit(self, record: dict[str, Any]) -> None:
        record["_seq"] = self._seq
        self._seq += 1
        self.events.append(record)

    def _on_put(self, bid: int, ts: float, unit: Unit, level: int) -> None:
        """Record every buffer entry, flagging the ones that filled the buffer."""
        saturated = level >= self.buffers[bid].capacity
        self.puts[bid].append((unit.index, round(ts, TS_DECIMALS), saturated))
        if saturated:
            self.saturation.setdefault((bid, unit.index), round(ts, TS_DECIMALS))

    # ------------------------------------------------------------- mechanics

    def _cycle_time(self, unit: Unit, sid: int, n_since_onset: int) -> float:
        st = self.line.station(sid)
        sigma = st.cycle_sigma_log
        z = float(unit.draws.cycle_z[sid])
        base = st.mean_cycle_s * st.model_multipliers.get(unit.model, 1.0)
        base *= float(np.exp(sigma * z - 0.5 * sigma * sigma))
        return base * self.fault.cycle_factor(sid, self.env.now, n_since_onset, unit.draws)

    def _quality_signal(self, unit: Unit, sid: int, n_since_onset: int) -> tuple[float, float]:
        """Return ``(measured_value, z)`` where z is deviation in healthy sd units."""
        st = self.line.station(sid)
        shift = self.fault.torque_shift_sd(sid, self.env.now, n_since_onset)
        z = float(unit.draws.torque_z[sid]) + shift
        return st.torque_mean + st.torque_sd * z, z

    def _apply_quality_fault(self, unit: Unit, sid: int, z: float) -> None:
        p = self.fault.defect_probability(sid, self.env.now, z)
        if p > 0.0 and float(unit.draws.quality_u[sid]) < p:
            unit.fault_defect = True
            unit.defect_code = getattr(self.fault, "defect_code", "PROCESS-SHIFT")
            unit.defect_station = sid

    # --------------------------------------------------------------- processes

    def _source(self) -> Any:
        arr = self.line.arrival
        cv = max(1e-6, arr.interarrival_cv)
        sigma = float(np.sqrt(np.log(1.0 + cv * cv)))
        max_units = int(self.horizon_s / max(1.0, arr.interarrival_mean_s) * 2.0) + 50
        first_buffer = self.buffers[self.line.station_ids[0]]

        for k in range(max_units):
            d = draws_for_unit(self.seed, k)
            gap = arr.interarrival_mean_s * float(np.exp(sigma * d.interarrival_z - 0.5 * sigma * sigma))
            if d.part_delay_u < arr.part_delay_probability:
                gap += arr.part_delay_median_s * float(np.exp(arr.part_delay_sigma_log * d.part_delay_z))
            yield self.env.timeout(gap)

            unit = Unit(index=k, vin=f"LS{k:06d}", model=self._model_for(d.model_u), draws=d)
            if d.base_defect_u < self.line.base_defect_rate:
                unit.base_defect = True
                codes = self.line.base_defect_codes
                unit.defect_code = codes[min(len(codes) - 1, int(d.base_defect_code_u * len(codes)))]
                ids = self.line.station_ids[:-1]
                unit.defect_station = ids[min(len(ids) - 1, int(d.base_defect_station_u * len(ids)))]
            unit.released_ts = self.env.now
            self.units.append(unit)
            yield first_buffer.put(unit)

    def _station(self, sid: int) -> Any:
        st = self.line.station(sid)
        ids = self.line.station_ids
        is_last = sid == ids[-1]
        nxt = None if is_last else ids[ids.index(sid) + 1]
        is_fault_station = self.fault.station == sid
        onset = self.fault.onset_s

        while True:
            unit: Unit = yield self.buffers[sid].get()
            t_start = self.env.now

            n_since = 0
            if is_fault_station and onset is not None and t_start >= onset:
                n_since = self._fault_count
                self._fault_count += 1

            ct = self._cycle_time(unit, sid, n_since)
            yield self.env.timeout(ct)

            value, z = self._quality_signal(unit, sid, n_since)
            unit.torque[sid] = value
            self._apply_quality_fault(unit, sid, z)
            unit.build_ts[sid] = self.env.now
            self._station_counts[sid] += 1

            if nxt is not None:
                yield self.buffers[nxt].put(unit)
            t_leave = self.env.now

            if st.instrumented:
                self._emit({"ts": round(t_start, TS_DECIMALS), "station": sid,
                            "vin": unit.vin, "event": "start"})
                self._emit({"ts": round(t_leave, TS_DECIMALS), "station": sid,
                            "vin": unit.vin, "event": "finish",
                            "cycle_time": round(ct, TS_DECIMALS),
                            "quality_signal": round(value, 4)})
            elif self._station_counts[sid] % st.checklist_every == 0:
                p_fail = min(0.9, 0.015 + 0.35 * max(0.0, z - 1.0))
                passed = float(unit.draws.checklist_u[sid]) >= p_fail
                self._emit({"ts": round(t_leave, TS_DECIMALS), "station": sid,
                            "vin": unit.vin, "event": "checklist", "pass": bool(passed)})

            if is_last:
                failed = unit.base_defect or unit.fault_defect
                unit.inspection_ts = round(t_leave, TS_DECIMALS)
                unit.inspection_result = "fail" if failed else "pass"
                self._emit({"ts": unit.inspection_ts, "station": sid, "vin": unit.vin,
                            "event": "inspection", "result": unit.inspection_result,
                            "defect_code": unit.defect_code if failed else "NONE"})
                self._completed.append(unit)

    # ------------------------------------------------------------------- run

    def run(self) -> RunResult:
        """Execute the simulation to the horizon and return its raw output."""
        self.env.process(self._source())
        for sid in self.line.station_ids:
            self.env.process(self._station(sid))
        self.env.run(until=self.horizon_s)
        self.events.sort(key=lambda e: (e["ts"], e["_seq"]))
        for e in self.events:
            e.pop("_seq", None)
        return RunResult(
            events=self.events,
            saturation=self.saturation,
            puts=self.puts,
            units=self.units,
            horizon_s=self.horizon_s,
            n_released=len(self.units),
            n_completed=len(self._completed),
        )


def simulate(line: LineConfig, fault: Fault, seed: int, horizon_s: float) -> RunResult:
    """Run one simulation pass. Deterministic in ``(line, fault, seed, horizon_s)``."""
    return LineSimulation(line, fault, seed, horizon_s).run()
