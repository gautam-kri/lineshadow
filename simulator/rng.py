"""Per-unit random substreams (common random numbers).

Every stochastic quantity a unit will ever need is drawn once, up front, from an
RNG seeded on ``(run_seed, unit_index)`` in a fixed order. Two consequences that
the rest of the system depends on:

1. Randomness is independent of SimPy's event ordering, so a run is
   byte-reproducible under ``--seed``.
2. The faulted run and its counterfactual twin see *identical* draws, so any
   difference between them is attributable to the injected fault alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_STATIONS = 64


@dataclass(frozen=True)
class UnitDraws:
    """The full random vector for one unit, drawn in a fixed order."""

    index: int
    model_u: float
    interarrival_z: float
    part_delay_u: float
    part_delay_z: float
    base_defect_u: float
    base_defect_code_u: float
    base_defect_station_u: float
    cycle_z: np.ndarray
    torque_z: np.ndarray
    slowdown_u: np.ndarray
    slowdown_mult_u: np.ndarray
    quality_u: np.ndarray
    checklist_u: np.ndarray


def draws_for_unit(run_seed: int, index: int) -> UnitDraws:
    """Draw the complete random vector for unit ``index`` of run ``run_seed``."""
    rng = np.random.default_rng([int(run_seed), int(index)])
    return UnitDraws(
        index=index,
        model_u=float(rng.random()),
        interarrival_z=float(rng.standard_normal()),
        part_delay_u=float(rng.random()),
        part_delay_z=float(rng.standard_normal()),
        base_defect_u=float(rng.random()),
        base_defect_code_u=float(rng.random()),
        base_defect_station_u=float(rng.random()),
        cycle_z=rng.standard_normal(MAX_STATIONS),
        torque_z=rng.standard_normal(MAX_STATIONS),
        slowdown_u=rng.random(MAX_STATIONS),
        slowdown_mult_u=rng.random(MAX_STATIONS),
        quality_u=rng.random(MAX_STATIONS),
        checklist_u=rng.random(MAX_STATIONS),
    )
