"""Configuration loading for the line topology and scenario files.

All durations are seconds. Conversion to minutes happens only at reporting
boundaries (``eval`` and ``app``), never inside the simulator or twin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LINE_CONFIG = REPO_ROOT / "config" / "line.yaml"

FAULT_FAMILIES = ("none", "drift", "slowdown", "quality")

TUNING_SEED_RANGE = (1000, 1999)
HOLDOUT_SEED_RANGE = (9000, 9999)


@dataclass(frozen=True)
class StationConfig:
    """Static engineering data for one station. Not ground truth."""

    id: int
    name: str
    zone: str
    mean_cycle_s: float
    cycle_sigma_log: float
    buffer_capacity: int
    instrumented: bool
    torque_mean: float
    torque_sd: float
    model_multipliers: dict[str, float]
    checklist_every: int = 10


@dataclass(frozen=True)
class ArrivalConfig:
    interarrival_mean_s: float
    interarrival_cv: float
    part_delay_probability: float
    part_delay_median_s: float
    part_delay_sigma_log: float
    source: str = "defaults"


@dataclass(frozen=True)
class LineConfig:
    """The full plant model: topology, timing and instrumentation coverage."""

    n_stations: int
    takt_time_s: float
    inspection_station: int
    zones: dict[str, tuple[int, int]]
    models: dict[str, float]
    arrival: ArrivalConfig
    base_defect_rate: float
    base_defect_codes: list[str]
    stations: dict[int, StationConfig]
    quality_source: str = "defaults"

    def station(self, sid: int) -> StationConfig:
        return self.stations[sid]

    @property
    def station_ids(self) -> list[int]:
        return sorted(self.stations)

    @property
    def instrumented_ids(self) -> list[int]:
        return [s for s in self.station_ids if self.stations[s].instrumented]

    @property
    def uninstrumented_ids(self) -> list[int]:
        return [s for s in self.station_ids if not self.stations[s].instrumented]

    def zone_of(self, sid: int) -> str:
        return self.stations[sid].zone


def load_line_config(path: str | Path = DEFAULT_LINE_CONFIG) -> LineConfig:
    """Load and validate ``config/line.yaml``."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["line"]
    arr = raw["arrival"]
    pd_ = arr["part_delay"]
    stations: dict[int, StationConfig] = {}
    for s in raw["stations"]:
        stations[int(s["id"])] = StationConfig(
            id=int(s["id"]),
            name=s["name"],
            zone=s["zone"],
            mean_cycle_s=float(s["mean_cycle_s"]),
            cycle_sigma_log=float(s["cycle_sigma_log"]),
            buffer_capacity=int(s["buffer_capacity"]),
            instrumented=bool(s["instrumented"]),
            torque_mean=float(s["torque_mean"]),
            torque_sd=float(s["torque_sd"]),
            model_multipliers={k: float(v) for k, v in s["model_multipliers"].items()},
            checklist_every=int(s.get("checklist_every", 10)),
        )
    if len(stations) != int(raw["n_stations"]):
        raise ValueError("station count does not match n_stations")
    q = raw["quality"]
    return LineConfig(
        n_stations=int(raw["n_stations"]),
        takt_time_s=float(raw["takt_time_s"]),
        inspection_station=int(raw["inspection_station"]),
        zones={k: (int(v[0]), int(v[1])) for k, v in raw["zones"].items()},
        models={k: float(v) for k, v in raw["models"].items()},
        arrival=ArrivalConfig(
            interarrival_mean_s=float(arr["interarrival_mean_s"]),
            interarrival_cv=float(arr["interarrival_cv"]),
            part_delay_probability=float(pd_["probability"]),
            part_delay_median_s=float(pd_["median_s"]),
            part_delay_sigma_log=float(pd_["sigma_log"]),
            source=str(pd_.get("source", "defaults")),
        ),
        base_defect_rate=float(q["base_defect_rate"]),
        base_defect_codes=list(q["base_defect_codes"]),
        stations=stations,
        quality_source=str(q.get("source", "defaults")),
    )


@dataclass(frozen=True)
class Scenario:
    """One simulation scenario: horizon, seed and (optionally) an injected fault."""

    scenario_id: str
    seed: int
    horizon_s: float
    split: str  # "tuning" | "holdout"
    fault: dict[str, Any] = field(default_factory=lambda: {"family": "none"})
    description: str = ""

    @property
    def family(self) -> str:
        return str(self.fault.get("family", "none"))

    @property
    def target_station(self) -> int | None:
        st = self.fault.get("station")
        return int(st) if st is not None else None

    @property
    def onset_s(self) -> float | None:
        on = self.fault.get("onset_s")
        return float(on) if on is not None else None

    @property
    def run_id(self) -> str:
        return f"{self.scenario_id}_seed{self.seed}"


def load_scenario(path: str | Path) -> Scenario:
    """Load a scenario YAML and enforce the tuning/holdout seed separation."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    split = raw.get("split") or p.parent.name
    sc = Scenario(
        scenario_id=str(raw["scenario_id"]),
        seed=int(raw["seed"]),
        horizon_s=float(raw["horizon_s"]),
        split=str(split),
        fault=dict(raw.get("fault") or {"family": "none"}),
        description=str(raw.get("description", "")),
    )
    if sc.family not in FAULT_FAMILIES:
        raise ValueError(f"unknown fault family {sc.family!r} in {p}")
    lo, hi = TUNING_SEED_RANGE if sc.split == "tuning" else HOLDOUT_SEED_RANGE
    if not lo <= sc.seed <= hi:
        raise ValueError(
            f"{p}: seed {sc.seed} outside the {sc.split} range {lo}-{hi}; "
            "tuning and holdout seed ranges must stay disjoint"
        )
    return sc


def scenario_dir(split: str) -> Path:
    return REPO_ROOT / "config" / "scenarios" / split


def list_scenarios(split: str) -> list[Scenario]:
    """Load every scenario in a split, sorted by scenario_id."""
    paths = sorted(scenario_dir(split).glob("*.yaml"))
    return sorted((load_scenario(p) for p in paths), key=lambda s: s.scenario_id)
