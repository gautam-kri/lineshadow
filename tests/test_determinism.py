"""Determinism and ground-truth integrity of the simulator."""

from __future__ import annotations

import json

import pytest

from simulator.config import HOLDOUT_SEED_RANGE, TUNING_SEED_RANGE, Scenario, load_scenario
from simulator.runner import read_jsonl, run_scenario
from tests.conftest import make_scenario


def test_same_seed_gives_byte_identical_events(tmp_path, line, drift_scenario):
    a = run_scenario(drift_scenario, line, out_root=tmp_path / "a")
    b = run_scenario(drift_scenario, line, out_root=tmp_path / "b")
    assert a.events_path.read_bytes() == b.events_path.read_bytes()
    assert a.events_path.stat().st_size > 0


def test_different_seed_gives_different_events(tmp_path, line):
    s1 = make_scenario("t", 1201, {"family": "none"})
    s2 = make_scenario("t", 1202, {"family": "none"})
    a = run_scenario(s1, line, out_root=tmp_path / "a")
    b = run_scenario(s2, line, out_root=tmp_path / "b")
    assert a.events_path.read_bytes() != b.events_path.read_bytes()


def test_control_scenario_counterfactual_is_identical(tmp_path, line, control_scenario):
    """Common random numbers: with no fault, both passes must coincide exactly."""
    art = run_scenario(control_scenario, line, out_root=tmp_path)
    assert art.events_path.read_bytes() == art.counterfactual_path.read_bytes()
    assert art.ground_truth["queue_forming"] is False
    assert art.ground_truth["throughput_loss_units"] == 0


def test_fault_diverges_from_counterfactual(tmp_path, line, drift_scenario):
    art = run_scenario(drift_scenario, line, out_root=tmp_path)
    assert art.events_path.read_bytes() != art.counterfactual_path.read_bytes()
    gt = art.ground_truth
    assert gt["queue_forming"] is True
    assert gt["queue_formation_ts"] > gt["onset_s"]
    assert gt["queue_formation_buffer"] == 12


def test_buffer_levels_are_never_emitted(tmp_path, line, drift_scenario):
    """The twin must infer buffer state; the stream may not hand it over."""
    art = run_scenario(drift_scenario, line, out_root=tmp_path)
    events = read_jsonl(art.events_path)
    kinds = {e["event"] for e in events}
    assert kinds <= {"start", "finish", "checklist", "inspection"}
    for e in events:
        assert not any("buffer" in k or "queue" in k or "level" in k for k in e)


def test_uninstrumented_stations_emit_only_checklists(tmp_path, line, drift_scenario):
    art = run_scenario(drift_scenario, line, out_root=tmp_path)
    events = read_jsonl(art.events_path)
    uninstr = set(line.uninstrumented_ids)
    for e in events:
        if e["station"] in uninstr:
            assert e["event"] == "checklist", f"leak from uninstrumented station: {e}"
    seen = {e["station"] for e in events if e["event"] == "checklist"}
    assert seen and seen <= uninstr


def test_quality_defects_surface_only_at_final_inspection(tmp_path, line, quality_scenario):
    art = run_scenario(quality_scenario, line, out_root=tmp_path)
    q = art.ground_truth["quality"]
    assert q["n_affected"] > 0
    assert q["escape_lag_s"] > 600.0, "the escape lag is the whole point; keep it"
    events = read_jsonl(art.events_path)
    fails = [e for e in events if e["event"] == "inspection" and e["result"] == "fail"]
    assert fails and all(e["station"] == line.inspection_station for e in fails)


def test_ground_truth_json_is_written_and_complete(tmp_path, line, drift_scenario):
    art = run_scenario(drift_scenario, line, out_root=tmp_path)
    gt = json.loads(art.ground_truth_path.read_text(encoding="utf-8"))
    for key in ("fault", "target_station", "onset_s", "queue_forming",
                "queue_formation_ts", "throughput_loss_units", "seed"):
        assert key in gt


@pytest.mark.parametrize("split,seed,ok", [
    ("tuning", 1500, True), ("tuning", 9500, False),
    ("holdout", 9500, True), ("holdout", 1500, False),
])
def test_seed_ranges_stay_disjoint(tmp_path, split, seed, ok):
    path = tmp_path / f"{split}.yaml"
    path.write_text(
        f"scenario_id: s\nsplit: {split}\nseed: {seed}\nhorizon_s: 100\nfault:\n  family: none\n",
        encoding="utf-8",
    )
    if ok:
        assert load_scenario(path).seed == seed
    else:
        with pytest.raises(ValueError, match="outside the"):
            load_scenario(path)


def test_shipped_scenarios_respect_their_seed_ranges():
    from simulator.config import list_scenarios
    for sc in list_scenarios("tuning"):
        assert TUNING_SEED_RANGE[0] <= sc.seed <= TUNING_SEED_RANGE[1]
    for sc in list_scenarios("holdout"):
        assert HOLDOUT_SEED_RANGE[0] <= sc.seed <= HOLDOUT_SEED_RANGE[1]
    tuning = {s.seed for s in list_scenarios("tuning")}
    holdout = {s.seed for s in list_scenarios("holdout")}
    assert not (tuning & holdout)
    assert isinstance(list_scenarios("holdout")[0], Scenario)
