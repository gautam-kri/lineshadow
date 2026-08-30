"""Turning cached candidates into alerts at a chosen sensitivity.

The twin stores every candidate scoring at or above the sensitivity-1 emission
floor. Selecting alerts is then two steps:

1. keep candidates whose score clears ``threshold(sensitivity)``, which is
   decreasing in sensitivity, so the kept set grows monotonically; then
2. thin each key's kept candidates with a greedy earliest-first minimum-gap pass.

Step 2 preserves the monotonicity of step 1: greedy earliest-first selection
under a minimum-gap constraint is *optimal* for cardinality, so a superset of
candidates can never yield fewer alerts than a subset. That is what makes the
false-alarms-per-shift curve weakly non-decreasing in sensitivity by
construction rather than by luck.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .config import TwinConfig


def _thin(candidates: list[dict[str, Any]], refractory_s: float,
          key: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    """Greedy earliest-first minimum-gap thinning, independently per key."""
    ordered = sorted(candidates, key=lambda c: (c["ts"], str(key(c))))
    if refractory_s <= 0:
        return ordered
    last: dict[Any, float] = {}
    kept: list[dict[str, Any]] = []
    for cand in ordered:
        k = key(cand)
        prev = last.get(k)
        if prev is None or cand["ts"] - prev >= refractory_s:
            kept.append(cand)
            last[k] = cand["ts"]
    return kept


def select_l1(candidates: Iterable[dict[str, Any]], cfg: TwinConfig,
              sensitivity: float | None = None) -> list[dict[str, Any]]:
    """L1 alerts at a given sensitivity."""
    t = cfg.l1_threshold(sensitivity)
    kept = [c for c in candidates if c["severity_score"] >= t]
    return _thin(kept, float(cfg.l1["refractory_s"]), lambda c: (c["station"], c["signal"]))


def select_l2(candidates: Iterable[dict[str, Any]], cfg: TwinConfig,
              sensitivity: float | None = None) -> list[dict[str, Any]]:
    """L2 predicted starve/block alerts at a given sensitivity."""
    t = cfg.l2_threshold(sensitivity)
    kept = [c for c in candidates if c["confidence"] >= t]
    return _thin(kept, float(cfg.l2["refractory_s"]), lambda c: (c["station"], c["kind"]))


def select_l3(candidates: Iterable[dict[str, Any]], cfg: TwinConfig,
              sensitivity: float | None = None) -> list[dict[str, Any]]:
    """L3 at-risk VIN flags at a given sensitivity."""
    t = cfg.l3_threshold(sensitivity)
    kept = [c for c in candidates if c["risk_score"] >= t]
    return _thin(kept, float(cfg.l3["refractory_s"]), lambda c: (c["vin"],))


def select_all(output: dict[str, Any], cfg: TwinConfig,
               sensitivity: float | None = None) -> dict[str, list[dict[str, Any]]]:
    """Apply the master sensitivity across all three layers at once."""
    return {
        "l1": select_l1(output.get("l1_candidates", []), cfg, sensitivity),
        "l2": select_l2(output.get("l2_candidates", []), cfg, sensitivity),
        "l3": select_l3(output.get("l3_candidates", []), cfg, sensitivity),
    }


def station_alerts(output: dict[str, Any], cfg: TwinConfig,
                   sensitivity: float | None = None) -> list[dict[str, Any]]:
    """All station-addressed alerts (L1 + L2), severity-ranked, for the operator feed."""
    sel = select_all(output, cfg, sensitivity)
    rows: list[dict[str, Any]] = []
    for a in sel["l1"]:
        rows.append({**a, "rank_score": a["severity_score"] * a["confidence"]})
    for a in sel["l2"]:
        rows.append({**a, "rank_score": a["confidence"]})
    rows.sort(key=lambda r: (-r["rank_score"], r["ts"]))
    return rows
