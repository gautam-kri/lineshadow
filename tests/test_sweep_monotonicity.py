"""The sensitivity knob must behave: more sensitivity, never fewer alerts.

Strict monotonicity is not asserted -- that would flake and end up deleted. What
is asserted is weak monotonicity with a small tolerance, averaged across control
runs, plus the structural property the whole design rests on: at a higher
sensitivity the alert set is a superset, because thresholds fall monotonically
and the greedy minimum-gap thinning is cardinality-optimal.
"""

from __future__ import annotations

import pytest

from eval.matching import load_eval_config
from eval.metrics import aggregate, score_scenario
from eval.sweep import sensitivity_points, sweep
from twin.thresholds import select_all, select_l1

from tests.conftest import make_scenario, run_twin

TOLERANCE = 0.05  # a step may dip by at most 5% of the previous step's rate


@pytest.fixture(scope="module")
def eval_cfg():
    return load_eval_config()


@pytest.fixture(scope="module")
def control_outputs(tmp_path_factory, line, twin_config):
    """Three independent control runs, twin output only."""
    root = tmp_path_factory.mktemp("sweep_controls")
    outputs = []
    for i, seed in enumerate((1120, 1121, 1122)):
        scenario = make_scenario(f"sweep_control_{i}", seed, {"family": "none"})
        output, gt = run_twin(scenario, line, root / str(seed))
        outputs.append((scenario, output, gt))
    return outputs


def test_false_alarms_per_shift_is_weakly_non_decreasing(
        control_outputs, twin_config, eval_cfg):
    rates = []
    for s in sensitivity_points(eval_cfg.sweep_points):
        scores = [score_scenario(gt, select_all(out, twin_config, s), eval_cfg)
                  for _, out, gt in control_outputs]
        rates.append(aggregate(scores, eval_cfg)["false_alarms_per_shift"]["mean"])

    assert rates[-1] > rates[0], "the sensitivity knob does nothing at all"
    for i in range(1, len(rates)):
        floor = rates[i - 1] * (1.0 - TOLERANCE)
        assert rates[i] >= floor, (
            f"false alarms/shift fell from {rates[i - 1]:.3f} to {rates[i]:.3f} "
            f"between sensitivity steps {i - 1} and {i}, beyond the "
            f"{TOLERANCE:.0%} sampling-noise tolerance"
        )


def test_alert_sets_are_strictly_nested(control_outputs, twin_config):
    """The structural guarantee: a higher sensitivity never drops an alert.

    Thresholds fall monotonically with sensitivity, so the surviving candidate
    set only grows; and greedy earliest-first selection under a minimum-gap
    constraint is optimal for cardinality, so thinning a superset can never
    return fewer alerts than thinning a subset.
    """
    for _, output, _ in control_outputs:
        counts = [len(select_l1(output["l1_candidates"], twin_config, s))
                  for s in sensitivity_points(12)]
        for lo, hi in zip(counts, counts[1:]):
            assert hi >= lo, f"alert count fell from {lo} to {hi} as sensitivity rose"


def test_thresholds_fall_monotonically_with_sensitivity(twin_config):
    points = sensitivity_points(12)
    for name, fn in (("l1", twin_config.l1_threshold),
                     ("l2", twin_config.l2_threshold),
                     ("l3", twin_config.l3_threshold)):
        values = [fn(s) for s in points]
        assert values == sorted(values, reverse=True), f"{name} thresholds are not monotone"
        assert values[0] > values[-1], f"{name} threshold does not respond to sensitivity"


def test_sweep_reports_every_sensitivity_point(control_outputs, twin_config, eval_cfg):
    from eval.harness import ScenarioResult

    results = [ScenarioResult(scenario=sc, ground_truth=gt, twin_output=out,
                              run_dir=None)  # type: ignore[arg-type]
               for sc, out, gt in control_outputs]
    rows = sweep(results, twin_cfg=twin_config, eval_cfg=eval_cfg)
    assert len(rows) == eval_cfg.sweep_points
    assert rows[0]["sensitivity"] == 0.0
    assert rows[-1]["sensitivity"] == 1.0
    for row in rows:
        assert row["false_alarms_per_shift"] is not None
        assert row["recall"] is None or 0.0 <= row["recall"] <= 1.0


def test_containment_is_weakly_non_decreasing_in_sensitivity(
        tmp_path, line, twin_config, eval_cfg, quality_scenario):
    """Raising sensitivity must not lose units that were already contained."""
    output, gt = run_twin(quality_scenario, line, tmp_path)
    rates = []
    for s in sensitivity_points(eval_cfg.sweep_points):
        score = score_scenario(gt, select_all(output, twin_config, s), eval_cfg)
        rates.append(score.containment_rate)
    assert all(r is not None for r in rates)
    for lo, hi in zip(rates, rates[1:]):
        assert hi >= lo - 1e-9, f"containment fell from {lo:.3f} to {hi:.3f}"
