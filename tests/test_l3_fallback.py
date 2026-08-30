"""The pipeline must run, and L3 must still flag, with no trained model on disk.

``models/l3.joblib`` is optional. These tests cover the three states it can be
in -- absent, present-but-unloadable, and present-and-valid -- and require the
first two to degrade to the unsupervised path rather than failing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from simulator.runner import read_jsonl, run_scenario
from twin.config import load_twin_config
from twin.l3_defect import L3DefectCorrelator
from twin.thresholds import select_l3
from twin.twin import DigitalTwin

from tests.conftest import run_twin


def test_model_file_absent_still_flags_unsupervised(tmp_path, line, quality_scenario):
    cfg = load_twin_config()
    cfg.l3["model_path"] = str(tmp_path / "definitely_not_here.joblib")
    assert not os.path.exists(cfg.l3["model_path"])

    output, gt = run_twin(quality_scenario, line, tmp_path, cfg=cfg)
    flags = select_l3(output["l3_candidates"], cfg)
    assert flags, "no L3 flags produced without a model file"
    assert output["l3_summary"]["model_source"] in ("none", "online")
    assert any(f["basis"] == "unsupervised" for f in flags)


def test_unloadable_model_degrades_instead_of_crashing(tmp_path, line):
    """A corrupt model file must not take the pipeline down."""
    bad = tmp_path / "corrupt.joblib"
    bad.write_bytes(b"this is not a joblib payload")
    cfg = load_twin_config()
    cfg.l3["model_path"] = str(bad)
    correlator = L3DefectCorrelator(line, cfg)
    assert correlator.model is None
    assert correlator.model_source == "none"


def test_full_pipeline_runs_end_to_end_without_model(
        tmp_path, line, quality_scenario, repo_root):
    """The shipped entrypoint, in a subprocess, with models/ pointed somewhere empty."""
    art = run_scenario(quality_scenario, line, out_root=tmp_path / "sim")

    cfg_path = tmp_path / "twin_nomodel.yaml"
    raw = (repo_root / "config" / "twin.yaml").read_text(encoding="utf-8")
    raw = raw.replace("model_path: models/l3.joblib",
                      f"model_path: {(tmp_path / 'absent.joblib').as_posix()}")
    cfg_path.write_text(raw, encoding="utf-8", newline="\n")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    proc = subprocess.run(
        [sys.executable, "-m", "twin", "--events", str(art.events_path),
         "--out", str(tmp_path / "out"), "--config", str(cfg_path)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr

    output = json.loads((tmp_path / "out" / "twin_output.json").read_text(encoding="utf-8"))
    assert output["l3_candidates"], "L3 produced nothing on the fallback path"
    assert output["alerts_at_configured_sensitivity"]["l3"]


def test_valid_model_is_used_and_marked_calibrated(tmp_path, line, quality_scenario):
    """With a real model on disk, flags must be attributed to it."""
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 5))
    y = (x[:, 0] + x[:, 3] > 0).astype(int)
    model = LogisticRegression(max_iter=500).fit(x, y)
    path = tmp_path / "l3.joblib"
    joblib.dump(model, path)

    cfg = load_twin_config()
    cfg.l3["model_path"] = str(path)
    art = run_scenario(quality_scenario, line, out_root=tmp_path / "sim")
    output = DigitalTwin(line, cfg).run(read_jsonl(art.events_path))

    assert output["l3_summary"]["model_source"] == "file"
    assert output["l3_summary"]["calibrated"] is True
    flags = select_l3(output["l3_candidates"], cfg)
    assert flags
    assert any(f["evidence"]["calibrated_probability"] is not None for f in flags)


# ------------------------------------------------------- training leakage guard


def test_training_refuses_holdout_scenarios():
    """A model trained on holdout data would silently invalidate the holdout report."""
    import pytest

    from scripts.train_l3 import LeakageError, assert_tuning_only
    from simulator.config import list_scenarios

    tuning = list_scenarios("tuning")
    assert_tuning_only(tuning)  # the shipped tuning split must pass

    for bad in list_scenarios("holdout"):
        with pytest.raises(LeakageError):
            assert_tuning_only(tuning + [bad])


def test_training_refuses_a_tuning_id_carrying_a_holdout_seed():
    """The seed range is checked independently of the id, so a relabelled
    holdout scenario cannot sneak through."""
    import pytest

    from scripts.train_l3 import LeakageError, assert_tuning_only
    from tests.conftest import make_scenario

    disguised = make_scenario("tuning_looks_fine", 9001, {"family": "none"}, split="tuning")
    with pytest.raises(LeakageError, match="HOLDOUT range"):
        assert_tuning_only([disguised])
