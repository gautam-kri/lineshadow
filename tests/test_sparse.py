"""Sparse-sensor inference: unseen stations are localised, and never look green."""

from __future__ import annotations

from twin.sparse import build_segments, confidence_label
from twin.thresholds import select_l1

from tests.conftest import TEST_ONSET_S, run_twin


def _first_hit(output, cfg, station, onset):
    """Earliest alert naming a station within one position of ``station``."""
    alerts = select_l1(output["l1_candidates"], cfg)
    hits = [a for a in alerts if abs(a["station"] - station) <= 1 and a["ts"] >= onset]
    return min(hits, key=lambda a: a["ts"]) if hits else None


def _station(output, sid):
    return next(s for s in output["stations"] if s["station"] == sid)


def test_fault_at_uninstrumented_station_is_localised(
        tmp_path, line, twin_config, uninstrumented_drift_scenario):
    target = uninstrumented_drift_scenario.target_station
    assert not line.station(target).instrumented, "fixture must target an unseen station"

    output, gt = run_twin(uninstrumented_drift_scenario, line, tmp_path)
    hit = _first_hit(output, twin_config, target, TEST_ONSET_S)

    assert hit is not None, "no alert raised for a drift at an uninstrumented station"
    assert abs(hit["station"] - target) <= 1, \
        f"alert named station {hit['station']}, expected {target} +/- 1"
    assert hit["basis"] == "inferred"
    ev = hit["evidence"]
    assert ev["observability"] == "uninstrumented"
    assert ev["anchor_upstream_station"] < target < ev["anchor_downstream_station"]
    assert ev["transit_samples_used"] > 0


def test_inferred_confidence_is_strictly_lower_than_direct(
        tmp_path, line, twin_config, uninstrumented_drift_scenario, instrumented_drift_scenario):
    """The same fault shape, seen directly vs inferred, must not read the same."""
    uninstr_out, _ = run_twin(uninstrumented_drift_scenario, line, tmp_path / "u")
    instr_out, _ = run_twin(instrumented_drift_scenario, line, tmp_path / "i")

    u_target = uninstrumented_drift_scenario.target_station
    i_target = instrumented_drift_scenario.target_station

    u_hit = _first_hit(uninstr_out, twin_config, u_target, TEST_ONSET_S)
    i_hit = _first_hit(instr_out, twin_config, i_target, TEST_ONSET_S)
    assert u_hit is not None and i_hit is not None

    assert u_hit["confidence"] < i_hit["confidence"], (
        f"inferred confidence {u_hit['confidence']} not below "
        f"direct confidence {i_hit['confidence']}"
    )
    assert u_hit["confidence_label"] != "high"
    assert i_hit["confidence_label"] == "high"

    u_state = _station(uninstr_out, u_target)
    i_state = _station(instr_out, i_target)
    assert u_state["confidence"] < i_state["confidence"]
    assert u_state["cycle_band_s"] > i_state["cycle_band_s"], \
        "an inferred estimate must carry a wider uncertainty band than a measured one"


def test_unseen_stations_never_report_high_confidence(tmp_path, line, control_scenario):
    """A station the twin cannot see must render low-confidence, not green."""
    output, _ = run_twin(control_scenario, line, tmp_path)
    for snap in output["stations"]:
        if not snap["instrumented"]:
            assert snap["estimate_basis"] == "inferred"
            assert confidence_label(snap["confidence"]) != "high", (
                f"station {snap['station']} is uninstrumented but reports "
                f"confidence {snap['confidence']}"
            )
            assert snap["cycle_band_s"] > 0.0


def test_segments_with_two_unknowns_are_lowest_confidence(tmp_path, line, control_scenario):
    """Where both neighbours are unseen, the twin must widen further and say so."""
    multi = [s for s in build_segments(line) if s.n_unknown > 1 and s.upstream > 0]
    assert multi, "line config should contain at least one adjacent uninstrumented pair"
    single = [s for s in build_segments(line) if s.n_unknown == 1 and s.upstream > 0]

    output, _ = run_twin(control_scenario, line, tmp_path)
    multi_conf = _station(output, multi[0].unknown[0])["confidence"]
    single_conf = _station(output, single[0].unknown[0])["confidence"]
    assert multi_conf < single_conf
    assert confidence_label(multi_conf) == "low"


def test_buffer_levels_are_inferred_not_observed(tmp_path, line, control_scenario):
    """Buffer levels are never emitted, so the twin must derive them and say how."""
    output, _ = run_twin(control_scenario, line, tmp_path)
    bases = {s["buffer_basis"] for s in output["stations"]}
    assert "exact" in bases, "buffers between two instrumented stations are recoverable"
    assert "inferred" in bases, "buffers inside an unseen segment must be marked inferred"
    for snap in output["stations"]:
        if snap["buffer_basis"] == "inferred":
            assert snap["buffer_level_low"] <= snap["buffer_level"] <= snap["buffer_level_high"]
        if snap["buffer_level"] is not None:
            assert 0 <= snap["buffer_level"] <= snap["buffer_capacity"]
