"""Ground truth derived from a same-seed counterfactual baseline.

The twin never reads any of this. Only ``eval/`` may.

The subtle metric here is ``queue_formation_ts``. Buffers saturate during normal
operation too, so "first buffer hits capacity" would score the detector against
noise. Instead we run the identical seed twice -- once with the fault, once
without -- and, because both runs share per-unit random draws, look for the first
*sustained* divergence: a buffer that saturates for ``SUSTAIN_UNITS`` consecutive
units in the faulted run while the counterfactual leaves it unsaturated for those
same units. Requiring a run of consecutive units, rather than a single one,
rejects the one-off flips that chaotic trajectory divergence produces once the
two runs have drifted apart at all.
"""

from __future__ import annotations

from typing import Any

from .config import LineConfig, Scenario
from .engine import RunResult
from .faults import Fault

SUSTAIN_UNITS = 5


def first_fault_attributable_saturation(
    faulted: RunResult,
    counterfactual: RunResult,
    onset_s: float | None,
    sustain_units: int = SUSTAIN_UNITS,
) -> tuple[float, int, str] | None:
    """First sustained, fault-attributable buffer saturation as ``(ts, buffer, vin)``."""
    cf_sat = counterfactual.saturation_keys()
    vin_by_index = {u.index: u.vin for u in faulted.units}
    best: tuple[float, int, str] | None = None

    for bid, entries in faulted.puts.items():
        streak: list[tuple[float, int]] = []
        for idx, ts, saturated in entries:
            if onset_s is not None and ts < onset_s:
                streak = []
                continue
            if saturated and (bid, idx) not in cf_sat:
                streak.append((ts, idx))
                if len(streak) >= sustain_units:
                    ts0, idx0 = streak[0]
                    cand = (ts0, bid, vin_by_index.get(idx0, f"LS{idx0:06d}"))
                    if best is None or cand < best:
                        best = cand
                    break
            else:
                streak = []
    return best


def _quality_ground_truth(faulted: RunResult, fault: Fault) -> dict[str, Any]:
    station = fault.station
    onset = fault.onset_s or 0.0
    affected: list[dict[str, Any]] = []
    built_through = 0
    for u in faulted.units:
        build_ts = u.build_ts.get(station) if station is not None else None
        if build_ts is None or build_ts < onset:
            continue
        built_through += 1
        if u.fault_defect:
            affected.append({
                "vin": u.vin,
                "build_ts": round(build_ts, 3),
                "inspection_ts": u.inspection_ts,
                "inspection_result": u.inspection_result,
                "reached_inspection": u.inspection_ts is not None,
            })
    affected.sort(key=lambda a: a["build_ts"])
    inspected = [a["inspection_ts"] for a in affected if a["inspection_ts"] is not None]
    return {
        "affected_vins": affected,
        "n_affected": len(affected),
        "n_affected_inspected": len(inspected),
        "n_built_through_after_onset": built_through,
        "first_affected_build_ts": affected[0]["build_ts"] if affected else None,
        "first_affected_inspection_ts": min(inspected) if inspected else None,
        "escape_lag_s": (min(inspected) - affected[0]["build_ts"]) if inspected and affected else None,
    }


def build_ground_truth(
    scenario: Scenario,
    fault: Fault,
    faulted: RunResult,
    counterfactual: RunResult,
    line: LineConfig,
) -> dict[str, Any]:
    """Assemble the hidden ground-truth record for one scenario."""
    onset = fault.onset_s
    sat = None if fault.family == "none" else first_fault_attributable_saturation(
        faulted, counterfactual, onset
    )

    gt: dict[str, Any] = {
        "scenario_id": scenario.scenario_id,
        "split": scenario.split,
        "seed": scenario.seed,
        "horizon_s": scenario.horizon_s,
        "fault": fault.describe(),
        "target_station": fault.station,
        "target_station_instrumented": (
            line.station(fault.station).instrumented if fault.station is not None else None
        ),
        "onset_s": onset,
        "queue_forming": sat is not None,
        "queue_formation_ts": sat[0] if sat else None,
        "queue_formation_buffer": sat[1] if sat else None,
        "queue_formation_vin": sat[2] if sat else None,
        "queue_formation_sustain_units": SUSTAIN_UNITS,
        "throughput_faulted": faulted.n_completed,
        "throughput_counterfactual": counterfactual.n_completed,
        "throughput_loss_units": counterfactual.n_completed - faulted.n_completed,
        "n_released": faulted.n_released,
        "quality": None,
        "notes": [],
    }

    if fault.family == "quality":
        gt["quality"] = _quality_ground_truth(faulted, fault)
    if fault.family != "none" and sat is None:
        gt["notes"].append(
            "No fault-attributable buffer saturation occurred; the fault never formed a "
            "sustained queue. Lead time for this scenario must be scored onset-relative."
        )
    if fault.family == "none":
        gt["notes"].append(
            "Control scenario: no fault injected. Every alert produced here is by "
            "definition a false alarm."
        )
    return gt
