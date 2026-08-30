"""Detection and the freeze protocol.

The detection test uses a *shipped tuning* scenario at its real horizon, scored
with the real matching rule, so it fails if either the detector or the scoring
protocol regresses.
"""

from __future__ import annotations

import pytest

from eval.freeze_thresholds import FreezeError, freeze, read_freeze_metadata, verify
from eval.matching import (first_correct_alert, is_true_positive, load_eval_config,
                           names_live_fault, scoring_window)
from eval.metrics import score_scenario
from simulator.config import load_scenario
from twin.thresholds import select_all

from tests.conftest import run_twin


@pytest.fixture(scope="module")
def eval_cfg():
    return load_eval_config()


def test_tuning_drift_detected_with_positive_lead_time(
        tmp_path, line, twin_config, eval_cfg, repo_root):
    scenario = load_scenario(repo_root / "config" / "scenarios" / "tuning" / "tuning_drift_s12.yaml")
    output, gt = run_twin(scenario, line, tmp_path)
    assert gt["queue_forming"] is True

    alerts = select_all(output, twin_config)
    first = first_correct_alert(alerts["l1"], gt, eval_cfg)
    assert first is not None, "L1 raised no matching alert for a known drift scenario"

    lead_min = (gt["queue_formation_ts"] - first["ts"]) / 60.0
    assert lead_min > 0, f"L1 alerted {abs(lead_min):.1f} min AFTER the queue formed"
    assert first["ts"] >= gt["onset_s"], "a matched alert cannot predate fault onset"
    assert abs(first["station"] - gt["target_station"]) <= eval_cfg.station_tolerance

    score = score_scenario(gt, alerts, eval_cfg)
    assert score.detected is True
    assert score.lead_time_queue_min is not None and score.lead_time_queue_min > 0
    assert score.detection_vs_onset_min is None, \
        "a queue-forming fault must not also report an onset-relative lead time"


def test_alert_before_onset_is_a_false_positive(eval_cfg):
    """The rule that stops a constantly-alerting detector scoring perfect lead time."""
    gt = {
        "fault": {"family": "drift"}, "target_station": 12, "onset_s": 10000.0,
        "queue_forming": True, "queue_formation_ts": 15000.0,
    }
    early = {"layer": "L1", "ts": 9999.0, "station": 12}
    inside = {"layer": "L1", "ts": 10001.0, "station": 12}
    assert not is_true_positive(early, gt, eval_cfg)
    assert is_true_positive(inside, gt, eval_cfg)
    assert not names_live_fault(early, gt, eval_cfg)
    assert names_live_fault(inside, gt, eval_cfg)


def test_matching_respects_station_tolerance_and_margin(eval_cfg):
    gt = {
        "fault": {"family": "drift"}, "target_station": 12, "onset_s": 10000.0,
        "queue_forming": True, "queue_formation_ts": 15000.0,
    }
    assert is_true_positive({"layer": "L1", "ts": 11000.0, "station": 11}, gt, eval_cfg)
    assert is_true_positive({"layer": "L1", "ts": 11000.0, "station": 13}, gt, eval_cfg)
    assert not is_true_positive({"layer": "L1", "ts": 11000.0, "station": 14}, gt, eval_cfg)
    edge = 15000.0 + eval_cfg.match_margin_s
    assert is_true_positive({"layer": "L1", "ts": edge, "station": 12}, gt, eval_cfg)
    assert not is_true_positive({"layer": "L1", "ts": edge + 1, "station": 12}, gt, eval_cfg)
    # L2 is matched on the station it blames, not the station it is about.
    assert is_true_positive(
        {"layer": "L2", "ts": 11000.0, "station": 30, "cause_station": 12}, gt, eval_cfg)


def test_control_scenarios_have_no_scoring_window(eval_cfg):
    gt = {"fault": {"family": "none"}, "target_station": None, "onset_s": None,
          "queue_forming": False, "queue_formation_ts": None}
    assert scoring_window(gt, eval_cfg) is None
    assert not is_true_positive({"layer": "L1", "ts": 1.0, "station": 12}, gt, eval_cfg)


def test_non_queue_forming_fault_scored_against_onset(
        tmp_path, line, twin_config, eval_cfg, repo_root):
    scenario = load_scenario(
        repo_root / "config" / "scenarios" / "tuning" / "tuning_torque_drift_s21.yaml")
    output, gt = run_twin(scenario, line, tmp_path)
    assert gt["queue_forming"] is False
    assert gt["queue_formation_ts"] is None
    assert any("onset-relative" in n for n in gt["notes"])

    score = score_scenario(gt, select_all(output, twin_config), eval_cfg)
    assert score.detected is True
    assert score.lead_time_queue_min is None, "no queue formed, so there is nothing to lead"
    assert score.detection_vs_onset_min is not None


# ------------------------------------------------------------- freeze protocol


def test_shipped_freeze_matches_the_live_config():
    meta = verify()
    assert len(meta["source_sha256"]) == 64
    assert meta["source"].endswith("twin.yaml")


def test_freeze_hard_fails_on_a_changed_config(tmp_path, repo_root):
    source = tmp_path / "twin.yaml"
    source.write_bytes((repo_root / "config" / "twin.yaml").read_bytes())
    frozen = tmp_path / "twin.frozen.yaml"
    freeze(source, frozen, note="test")
    assert verify(source, frozen)["source_sha256"]

    source.write_text(source.read_text(encoding="utf-8") + "\n# a later edit\n",
                      encoding="utf-8", newline="\n")
    with pytest.raises(FreezeError, match="FROZEN CONFIG MISMATCH"):
        verify(source, frozen)


def test_missing_freeze_is_an_error_not_a_warning(tmp_path):
    with pytest.raises(FreezeError, match="does not exist"):
        read_freeze_metadata(tmp_path / "never_written.yaml")


def test_holdout_refuses_to_run_without_a_freeze(tmp_path, monkeypatch):
    """`run_holdout` must refuse, not warn, when the freeze is absent."""
    import eval.freeze_thresholds as ft
    import eval.run_holdout as rh

    monkeypatch.setattr(ft, "FROZEN_PATH", tmp_path / "absent.yaml")
    with pytest.raises(FreezeError, match="does not exist"):
        rh.run(verbose=False)
