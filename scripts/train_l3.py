"""Train the optional calibrated half of L3.

    python scripts/train_l3.py
    python scripts/train_l3.py --out models/l3.joblib

Trains a gradient-boosted classifier on features harvested from **tuning
scenarios only**, and saves it to ``models/l3.joblib``. The twin picks the file
up automatically if it is there and falls back cleanly to the unsupervised path
if it is not -- which is the behaviour ``tests/test_l3_fallback.py`` pins.

Leakage guard: every scenario is checked by split, by scenario-id prefix and by
seed range before a single row of it is used, and the script fails hard if a
holdout scenario appears anywhere in the training set. A model trained on
holdout data would silently invalidate every number in the holdout report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simulator.config import (HOLDOUT_SEED_RANGE, TUNING_SEED_RANGE, Scenario,
                              list_scenarios, load_line_config)
from simulator.runner import RUNS_ROOT, run_scenario
from twin.config import load_twin_config
from twin.l3_defect import FEATURE_NAMES
from twin.twin import DigitalTwin, stream_events

DEFAULT_OUT = REPO_ROOT / "models" / "l3.joblib"


class LeakageError(RuntimeError):
    """Raised when a holdout scenario reaches the training set."""


def assert_tuning_only(scenarios: list[Scenario]) -> None:
    """Three independent checks; any one of them failing stops the run."""
    holdout_ids = {s.scenario_id for s in list_scenarios("holdout")}
    lo, hi = HOLDOUT_SEED_RANGE
    tlo, thi = TUNING_SEED_RANGE
    for sc in scenarios:
        if sc.split != "tuning":
            raise LeakageError(f"{sc.scenario_id}: split is {sc.split!r}, not 'tuning'")
        if sc.scenario_id in holdout_ids or sc.scenario_id.startswith("holdout"):
            raise LeakageError(f"{sc.scenario_id}: holdout scenario id in the training set")
        if lo <= sc.seed <= hi:
            raise LeakageError(
                f"{sc.scenario_id}: seed {sc.seed} is inside the HOLDOUT range {lo}-{hi}")
        if not tlo <= sc.seed <= thi:
            raise LeakageError(
                f"{sc.scenario_id}: seed {sc.seed} is outside the tuning range {tlo}-{thi}")


def harvest(scenarios: list[Scenario], verbose: bool = True) -> tuple[list[list[float]], list[int]]:
    """Run the twin over each scenario and collect its (features, label) pairs.

    The features are exactly the ones L3 computes at build time, so what the model
    trains on is what it will see in production -- no separate feature pipeline to
    drift out of sync.
    """
    line = load_line_config()
    cfg = load_twin_config()
    cfg.l3["model_path"] = ""  # harvest with the unsupervised scorer, never a prior model

    features: list[list[float]] = []
    labels: list[int] = []
    for sc in scenarios:
        run_dir = RUNS_ROOT / sc.run_id
        events = run_dir / "events.jsonl"
        if not events.exists():
            run_scenario(sc, line, out_root=RUNS_ROOT)
        twin = DigitalTwin(line, cfg)
        twin.run(stream_events(str(events)))
        features.extend(twin.l3.features)
        labels.extend(twin.l3.labels)
        if verbose:
            print(f"  {sc.scenario_id:32s} +{len(twin.l3.labels):4d} labelled units "
                  f"({sum(twin.l3.labels)} failures)")
    return features, labels


def train(features: list[list[float]], labels: list[int], seed: int = 20260829) -> dict[str, Any]:
    """Fit a gradient-boosted classifier and report held-back-split performance."""
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import train_test_split

    x = np.asarray(features, dtype=float)
    y = np.asarray(labels, dtype=int)
    if y.sum() < 20 or (len(y) - y.sum()) < 20:
        raise RuntimeError(
            f"not enough signal to train: {int(y.sum())} failures in {len(y)} units. "
            "Add or lengthen quality scenarios in config/scenarios/tuning/."
        )

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=seed, stratify=y)
    model = GradientBoostingClassifier(
        n_estimators=200, learning_rate=0.05, max_depth=3, random_state=seed)
    model.fit(x_train, y_train)

    probability = model.predict_proba(x_test)[:, 1]
    metrics = {
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "positive_rate": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probability)), 4),
        "average_precision": round(float(average_precision_score(y_test, probability)), 4),
        "feature_importance": {
            name: round(float(value), 4)
            for name, value in zip(FEATURE_NAMES, model.feature_importances_)
        },
    }
    return {"model": model, "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/train_l3.py", description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=20260829)
    args = ap.parse_args(argv)

    scenarios = list_scenarios("tuning")
    try:
        assert_tuning_only(scenarios)
    except LeakageError as exc:
        print(f"\nREFUSING TO TRAIN — holdout leakage detected:\n  {exc}\n")
        return 2
    print(f"Leakage guard passed: {len(scenarios)} tuning scenarios, "
          f"seeds {min(s.seed for s in scenarios)}-{max(s.seed for s in scenarios)} "
          f"(holdout range {HOLDOUT_SEED_RANGE[0]}-{HOLDOUT_SEED_RANGE[1]} excluded)\n")

    print("Harvesting build-time features and inspection labels:")
    features, labels = harvest(scenarios)
    print(f"\nTotal: {len(labels)} labelled units, {sum(labels)} failures "
          f"({sum(labels) / max(1, len(labels)):.1%})")

    try:
        result = train(features, labels, args.seed)
    except RuntimeError as exc:
        print(f"\n{exc}")
        print("The twin runs fine without this model; L3 stays on its unsupervised path.")
        return 1

    import joblib
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(result["model"], args.out)

    metrics = result["metrics"]
    metrics["trained_from"] = [s.scenario_id for s in scenarios]
    metrics["seed_range_used"] = list(TUNING_SEED_RANGE)
    (args.out.with_suffix(".metrics.json")).write_text(
        json.dumps(metrics, indent=2), encoding="utf-8", newline="\n")

    print(f"\nwrote {args.out}")
    print(f"  ROC AUC           : {metrics['roc_auc']}")
    print(f"  average precision : {metrics['average_precision']} "
          f"(base rate {metrics['positive_rate']})")
    print("  feature importance:")
    for name, value in sorted(metrics["feature_importance"].items(), key=lambda kv: -kv[1]):
        print(f"    {name:28s} {value:.4f}")
    print("\nThe twin will pick this up automatically. Delete it to fall back to the "
          "unsupervised path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
