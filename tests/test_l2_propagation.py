"""L2: the forward projection must name the real cause and stay quiet on controls."""

from __future__ import annotations

from twin.thresholds import select_l2

from tests.conftest import TEST_ONSET_S, run_twin


def test_projection_names_the_true_cause_station(
        tmp_path, line, twin_config, drift_scenario):
    target = drift_scenario.target_station
    output, gt = run_twin(drift_scenario, line, tmp_path)
    alerts = select_l2(output["l2_candidates"], twin_config)

    assert alerts, "L2 produced no predictions for a queue-forming drift"
    causes = [a["cause_station"] for a in alerts if a["ts"] >= TEST_ONSET_S]
    assert causes, "no L2 predictions after fault onset"
    # The most-cited cause must be the faulted station or an immediate neighbour.
    dominant = max(set(causes), key=causes.count)
    assert abs(dominant - target) <= 1, f"L2 blamed station {dominant}, expected {target} +/- 1"


def test_predictions_are_arithmetic_and_evidenced(tmp_path, line, twin_config, drift_scenario):
    output, _ = run_twin(drift_scenario, line, tmp_path)
    alerts = select_l2(output["l2_candidates"], twin_config)
    assert alerts

    for a in alerts:
        assert a["kind"] in ("starve", "block")
        # predicted_ts is rounded to 0.1s for readability; allow that much slack.
        assert a["predicted_ts"] >= a["ts"] - 0.1, "a prediction must be about the future"
        ev = a["evidence"]
        for key in ("time_to_event_s", "rate_deficit_per_s", "buffer_level_at_projection",
                    "buffer_capacity", "percentile_projections_agreeing",
                    "cause_cycle_estimate_s", "demand_rate_per_s"):
            assert key in ev, f"L2 evidence missing {key}"
        assert ev["rate_deficit_per_s"] > 0
        # The headline time-to-event must be reproducible from the stated arithmetic.
        assert abs(ev["time_to_event_s"] - (a["predicted_ts"] - a["ts"])) < 1.5


def test_three_percentile_projections_drive_confidence(
        tmp_path, line, twin_config, drift_scenario):
    output, _ = run_twin(drift_scenario, line, tmp_path)
    alerts = select_l2(output["l2_candidates"], twin_config)
    agreements = {a["evidence"]["percentile_projections_agreeing"] for a in alerts}
    assert agreements <= {"1/3", "2/3", "3/3"}
    for a in alerts:
        agreeing = int(a["evidence"]["percentile_projections_agreeing"].split("/")[0])
        assert a["confidence"] <= agreeing / 3.0 + 1e-9, \
            "confidence must not exceed the share of percentile projections that agree"


def test_control_run_is_nearly_silent(tmp_path, line, twin_config, control_scenario):
    """On a line with no fault, L2 must not manufacture a bottleneck."""
    output, gt = run_twin(control_scenario, line, tmp_path)
    assert gt["queue_forming"] is False
    alerts = select_l2(output["l2_candidates"], twin_config)
    shifts = control_scenario.horizon_s / (7.5 * 3600.0)
    assert len(alerts) / shifts < 8.0, \
        f"{len(alerts)} L2 false alarms over {shifts:.1f} shifts is too noisy"
