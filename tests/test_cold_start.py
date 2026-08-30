"""L3 must flag at-risk units before any label exists to learn from.

If L3 were purely supervised it could not act until escapes had already reached
final inspection, which would make containment zero by construction. These tests
pin the unsupervised path: the first flag has to land before the first
fault-attributable inspection failure surfaces, and it has to be made without a
fitted model.
"""

from __future__ import annotations

import pytest

from twin.config import load_twin_config
from twin.l3_defect import first_flag_by_vin
from twin.thresholds import select_l3

from tests.conftest import run_twin


@pytest.fixture
def cold_start_config(tmp_path):
    """Twin config with no L3 model on disk -- the genuine cold-start condition.

    Pinned explicitly rather than left to depend on whether `models/l3.joblib`
    happens to exist: the point of this test is that L3 works *before* any label
    or model is available, so the test must create that state rather than assume it.
    """
    cfg = load_twin_config()
    cfg.l3["model_path"] = str(tmp_path / "no_model_here.joblib")
    return cfg


def test_l3_flags_before_the_first_escape_surfaces(
        tmp_path, line, cold_start_config, quality_scenario):
    twin_config = cold_start_config
    output, gt = run_twin(quality_scenario, line, tmp_path, cfg=twin_config)
    quality = gt["quality"]
    assert quality["n_affected"] > 0
    first_failure_ts = quality["first_affected_inspection_ts"]
    assert first_failure_ts is not None, "scenario produced no inspected escape"

    flags = select_l3(output["l3_candidates"], twin_config)
    assert flags, "L3 raised nothing at all"
    earliest = min(flags, key=lambda f: f["ts"])

    assert earliest["ts"] < first_failure_ts, (
        f"first L3 flag at {earliest['ts']:.0f}s, but the first escape had already "
        f"surfaced at {first_failure_ts:.0f}s -- the unsupervised path is not working"
    )
    assert earliest["basis"] == "unsupervised"
    assert earliest["evidence"]["calibrated_probability"] is None
    assert earliest["evidence"]["model_source"] == "none"


def test_cold_start_flag_names_the_right_station(
        tmp_path, line, cold_start_config, quality_scenario):
    twin_config = cold_start_config
    output, gt = run_twin(quality_scenario, line, tmp_path, cfg=twin_config)
    flags = select_l3(output["l3_candidates"], twin_config)
    first_failure_ts = gt["quality"]["first_affected_inspection_ts"]
    pre_label = [f for f in flags if f["ts"] < first_failure_ts]
    assert pre_label, "nothing flagged before the first escape"
    assert {f["suspect_station"] for f in pre_label} == {gt["target_station"]}


def test_containment_beats_the_do_nothing_baseline(
        tmp_path, line, twin_config, quality_scenario):
    """Share of affected units flagged before their own inspection timestamp."""
    output, gt = run_twin(quality_scenario, line, tmp_path)
    affected = [a for a in gt["quality"]["affected_vins"] if a["inspection_ts"] is not None]
    assert affected

    first_flag = first_flag_by_vin(select_l3(output["l3_candidates"], twin_config))
    contained = [
        a for a in affected
        if a["vin"] in first_flag and first_flag[a["vin"]] < a["inspection_ts"]
    ]
    containment = len(contained) / len(affected)
    assert containment > 0.5, f"containment {containment:.1%} is no better than guessing"


def test_calibration_identifies_the_predictive_station(
        tmp_path, line, twin_config, quality_scenario):
    """The supervised half must learn which station's signal actually predicts escapes."""
    output, gt = run_twin(quality_scenario, line, tmp_path)
    lift = output["l3_summary"]["station_lift"]
    assert lift, "no station lift computed despite inspection labels arriving"
    assert lift[0]["station"] == gt["target_station"]
    assert lift[0]["lift"] > 0.2
    assert output["l3_summary"]["labels_seen"] > 0


def test_control_run_flags_almost_nothing(tmp_path, line, twin_config, control_scenario):
    output, gt = run_twin(control_scenario, line, tmp_path)
    assert gt["quality"] is None
    flags = select_l3(output["l3_candidates"], twin_config)
    shifts = control_scenario.horizon_s / (7.5 * 3600.0)
    assert len(flags) / shifts < 5.0, f"{len(flags)} L3 false flags on a healthy line"


def test_early_flagging_survives_a_trained_model_being_present(
        tmp_path, line, twin_config, quality_scenario):
    """With a model on disk, the first flag must still beat the first escape.

    The calibrated half is meant to sharpen the primary score, not gate it, so
    adding a model must not delay the first flag past the point of usefulness.
    """
    output, gt = run_twin(quality_scenario, line, tmp_path, cfg=twin_config)
    flags = select_l3(output["l3_candidates"], twin_config)
    assert flags
    earliest = min(flags, key=lambda f: f["ts"])
    assert earliest["ts"] < gt["quality"]["first_affected_inspection_ts"]
