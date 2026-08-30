"""Shared pytest fixtures.

Tests use short horizons so the whole suite stays fast; the fault onsets are
scaled down to match, which keeps every scenario shape identical to the
full-length ones in ``config/scenarios/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simulator.config import Scenario, load_line_config  # noqa: E402
from simulator.runner import read_jsonl, run_scenario  # noqa: E402
from twin.config import load_twin_config  # noqa: E402
from twin.twin import DigitalTwin  # noqa: E402

# The twin ignores events until the line has filled (prime guard) and then needs
# a per-signal warm-up window, so a test fault must start well after both.
TEST_HORIZON_S = 36000.0
TEST_ONSET_S = 15000.0


@pytest.fixture(scope="session")
def line():
    return load_line_config()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def make_scenario(scenario_id: str, seed: int, fault: dict, split: str = "tuning",
                  horizon_s: float = TEST_HORIZON_S) -> Scenario:
    """Build an in-memory scenario without touching config/scenarios/."""
    return Scenario(scenario_id=scenario_id, seed=seed, horizon_s=horizon_s,
                    split=split, fault=fault, description="pytest fixture scenario")


@pytest.fixture(scope="session")
def drift_scenario() -> Scenario:
    """A strong cycle-time drift at instrumented bottleneck station 12."""
    return make_scenario("test_drift_s12", 1101, {
        "family": "drift", "station": 12, "onset_s": TEST_ONSET_S,
        "signal": "cycle_time", "shape": "linear",
        "magnitude_pct": 30, "ramp_units": 40,
    })


@pytest.fixture(scope="session")
def uninstrumented_drift_scenario() -> Scenario:
    """The same drift shape, but at uninstrumented station 34."""
    return make_scenario("test_drift_s34_uninstr", 1102, {
        "family": "drift", "station": 34, "onset_s": TEST_ONSET_S,
        "signal": "cycle_time", "shape": "linear",
        "magnitude_pct": 30, "ramp_units": 40,
    })


@pytest.fixture(scope="session")
def instrumented_drift_scenario() -> Scenario:
    """Matched control for the sparse test: same shape at instrumented station 33."""
    return make_scenario("test_drift_s33_instr", 1103, {
        "family": "drift", "station": 33, "onset_s": TEST_ONSET_S,
        "signal": "cycle_time", "shape": "linear",
        "magnitude_pct": 30, "ramp_units": 40,
    })


@pytest.fixture(scope="session")
def quality_scenario() -> Scenario:
    """A process shift whose defects only surface at final inspection."""
    return make_scenario("test_quality_s08", 1104, {
        "family": "quality", "station": 8, "onset_s": TEST_ONSET_S,
        "fail_probability": 0.45, "torque_shift_sigma": 2.6,
        "defect_code": "TORQUE-LOW",
    })


@pytest.fixture(scope="session")
def control_scenario() -> Scenario:
    return make_scenario("test_control", 1110, {"family": "none"})


@pytest.fixture(scope="session")
def twin_config():
    return load_twin_config()


def run_twin(scenario: Scenario, line, tmp_root: Path, cfg=None) -> tuple[dict, dict]:
    """Simulate a scenario, then run the twin on its event stream alone.

    Returns ``(twin_output, ground_truth)``. Tests may look at both; the twin
    itself is only ever handed the events.
    """
    art = run_scenario(scenario, line, out_root=tmp_root)
    cfg = cfg or load_twin_config()
    output = DigitalTwin(line, cfg).run(read_jsonl(art.events_path))
    return output, art.ground_truth
