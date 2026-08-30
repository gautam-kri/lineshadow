"""Render ``reports/holdout_report.md`` from the scored holdout bundle.

    python -m eval.report            # re-uses reports/holdout_results.json
    python -m eval.report --rerun    # re-scores first

Every number in the report is traceable: the frozen config hash, the holdout seed
range and the exact commands that reproduce it are all printed in the header.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Sequence

from simulator.config import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
RESULTS_PATH = REPORTS / "holdout_results.json"
REPORT_PATH = REPORTS / "holdout_report.md"


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _pct(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value * 100:.{digits}f}%"


def _signed(value: float | None, digits: int = 1) -> str:
    return "–" if value is None else f"{value:+.{digits}f}"


def _model_note(bundle: dict[str, Any]) -> str:
    """State plainly whether a trained L3 model was in play for these numbers."""
    info = bundle.get("l3_model") or {}
    source = info.get("source", "none")
    if source == "file":
        return (f"loaded from `{info.get('path')}` — {info.get('trained_on')}. "
                "L3's unsupervised path runs regardless; the model only sharpens it.")
    if source == "online":
        return ("none on disk; L3 fitted a logistic model online from inspection labels "
                "as they arrived during each run.")
    return "none — L3 ran on its unsupervised path alone."


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def render(bundle: dict[str, Any]) -> str:
    s = bundle["summary"]
    fa = s["false_alarms_per_shift"]
    freeze = bundle["freeze"]
    ev = bundle["eval_config"]
    line = bundle["line"]
    lo, hi = bundle["seed_range"]

    faulted = [r for r in bundle["scenarios"] if r["family"] != "none"]
    controls = [r for r in bundle["scenarios"] if r["family"] == "none"]
    parts: list[str] = []
    parts.append(f"""# Ninja — holdout validation report

> **Every figure below comes from sealed holdout scenarios that were never used
> for tuning.** Detector thresholds were calibrated exclusively against the
> *tuning* split's control runs and then frozen. `eval/run_holdout.py` refuses to
> produce this report unless the live `config/twin.yaml` still hashes to the
> frozen record, so no number here can have been produced by thresholds adjusted
> after seeing these scenarios.

| | |
|---|---|
| Generated | {dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")} |
| Frozen config | `{bundle['frozen_config']}` |
| Frozen at | {freeze['frozen_at_utc']} |
| Config SHA-256 | `{freeze['source_sha256']}` |
| Holdout seed range | **{lo}–{hi}** (tuning uses 1000–1999; the ranges are disjoint and enforced at load time) |
| Master sensitivity | {bundle['sensitivity']} |
| Line | {line['n_stations']} stations, {line['n_instrumented']} instrumented ({line['n_instrumented'] / line['n_stations']:.0%}), takt {line['takt_time_s']:.1f} s |
| Uninstrumented stations | {', '.join(str(x) for x in line['uninstrumented'])} |
| L3 calibrated model | {_model_note(bundle)} |
""")
    if freeze.get("note"):
        parts.append(f"> Freeze note: {freeze['note']}\n")

    parts.append(f"""## Headline results

| Metric | Value |
|---|---|
| Faults detected (recall) | **{s['n_detected']} / {s['n_faulted']}** |
| Alert precision | **{_pct(s['precision'])}** |
| Median lead time, queue-forming faults (n={s['queue_forming']['n']}) | **{_signed(s['queue_forming']['median_lead_time_min'])} min early** |
| Lead-time range, queue-forming | {_signed(s['queue_forming']['min_lead_time_min'])} to {_signed(s['queue_forming']['max_lead_time_min'])} min |
| Median detection vs onset, non-queue-forming (n={s['non_queue_forming']['n']}) | {_signed(s['non_queue_forming']['median_detection_vs_onset_min'])} min |
| Defect containment, quality faults (n={s['quality']['n']}) | **{_pct(s['quality']['mean_containment_rate'])}** ({s['quality']['total_contained']} / {s['quality']['total_affected']} affected units) |
| Median containment head start | {_fmt(s['quality']['median_units_early_min'])} min before the first escape surfaced |
| False alarms per shift (controls only, n={fa['n']}) | **{_fmt(fa['mean'], 2)}** {'' if fa['low'] is None else f"(95% CI {fa['low']:.2f}–{fa['high']:.2f})"} |
| Throughput lost to the injected faults | {s['throughput_loss_units_total']} units |

**Sign convention: positive lead time means the twin called it early.**

The two lead-time columns use different reference points and are never averaged
together. Queue-forming faults are scored against the timestamp at which a buffer
actually saturated because of the fault. Faults that never formed a queue have no
such reference, so they are scored against fault onset instead, which makes that
column a detection *latency* and therefore negative.
""")

    parts.append("## Per-scenario results\n")
    rows = []
    for r in faulted:
        rows.append([
            f"`{r['scenario_id']}`",
            r["family"],
            str(r["target_station"]),
            "**no**" if r["target_instrumented"] is False else "yes",
            "yes" if r["queue_forming"] else "no",
            "yes" if r["detected"] else "**NO**",
            _signed(r["lead_time_queue_min"]),
            _signed(r["detection_vs_onset_min"]),
            _pct(r["containment_rate"], 0),
            f"{r['first_alert_layer'] or '–'} / {r['first_alert_signal'] or '–'}",
            str(r["throughput_loss_units"]),
        ])
    parts.append(_table(
        ["scenario", "family", "station", "instrumented", "queue formed", "detected",
         "lead vs queue (min)", "detection vs onset (min)", "containment",
         "first alert", "units lost"],
        rows))

    parts.append(f"""
### Faults at stations the twin cannot see directly

{len([r for r in faulted if r['target_instrumented'] is False])} of {len(faulted)} holdout faults were injected at an **uninstrumented** station,
which emits no per-unit events at all. Those were detected purely from the timing
of neighbouring instrumented stations plus flow conservation across the
intervening buffers, and every such alert is reported at reduced confidence with
a wider uncertainty band — the twin never renders a station it cannot see as green.
""")

    parts.append("\n## Control scenarios (false-alarm measurement)\n")
    parts.append(f"""False alarms are measured **only** on control runs with no fault injected, where
every alert is false by construction. They are deliberately not derived from the
faulted runs: there, a correct alert that fires outside the scoring window cannot
be cleanly separated from a genuinely spurious one, so any false-alarm rate taken
from faulted runs would be measuring the scoring window rather than the detector.

One shift = {ev['shift_s'] / 3600:.1f} h. With n={fa['n']} control runs the interval is wide; it is
reported rather than hidden, and the lower bound is clamped at zero because a
rate cannot be negative.
""")
    control_rows = []
    for r in controls:
        shifts = r["horizon_s"] / ev["shift_s"]
        control_rows.append([f"`{r['scenario_id']}`", str(r["n_alerts"]),
                             f"{shifts:.1f}", f"{r['n_alerts'] / shifts:.2f}"])
    parts.append(_table(["control scenario", "alerts", "shifts", "alerts/shift"], control_rows))

    parts.append("\n## Threshold sweep\n")
    parts.append(f"""The twin runs once per scenario at the sensitivity-1 emission floor; each row
below is a re-threshold of those cached candidates, so all {ev['sweep_points']} points see an
identical candidate set. Alert selection is a score cut followed by a greedy
earliest-first minimum-gap thinning, and greedy earliest-first selection is
optimal for cardinality under a minimum-gap constraint — so a higher sensitivity
can never yield fewer alerts than a lower one. The monotonicity of the
false-alarm column is therefore structural, not empirical.

Full data: [`threshold_sweep.csv`](threshold_sweep.csv) · interactive plot: [`threshold_sweep.html`](threshold_sweep.html)
""")
    sweep_rows = []
    for row in bundle["sweep"]:
        sweep_rows.append([
            f"{row['sensitivity']:.2f}",
            f"{row['l1_severity_threshold']:.2f}",
            _pct(row["precision"], 0),
            _pct(row["recall"], 0),
            _signed(row["median_lead_time_min"]),
            _pct(row["mean_containment_rate"], 0),
            f"{row['false_alarms_per_shift']:.2f}",
            f"{row['false_alarms_per_shift_low']:.2f}–{row['false_alarms_per_shift_high']:.2f}",
        ])
    parts.append(_table(
        ["sensitivity", "L1 threshold", "precision", "recall", "median lead (min)",
         "containment", "false alarms/shift", "95% CI"],
        sweep_rows))

    parts.append(f"""
## How these numbers are defined

**Ground truth by counterfactual.** Each scenario is simulated twice from the same
seed — once with the fault, once without — with per-unit random draws shared
between the two runs, so any difference between them is attributable to the fault
alone. `queue_formation_ts` is the first buffer saturation that occurs in the
faulted run for {bundle.get('queue_formation_sustain_units', 5)} consecutive units
that did *not* saturate that buffer in the counterfactual. Defining it as "any buffer reaching capacity" would
score the detector against noise, because buffers saturate during normal
operation too; requiring a sustained divergence also rejects the one-off flips
that chaotic trajectory divergence produces once two runs have drifted apart.

**Alert matching.** An alert is matched if it names the faulted station or an
immediate neighbour (tolerance ±{ev['station_tolerance']}) *and* fires within
`[onset, queue_formation + {ev['match_margin_s'] / 60:.0f} min]`, or within
`[onset, onset + {ev['onset_window_s'] / 60:.0f} min]` for faults that never form a
queue. **An alert fired before fault onset is a false positive, not an early
win** — without that rule a detector that alerted constantly would score perfect
lead time. L2 predictions are matched on their `cause_station`, since that is the
diagnosis being scored.

**Precision** uses a deliberately weaker, separately reported rule: an alert
counts as correct if it names the faulted station at any point after onset, while
the fault is still live. An alert naming the right station three hours after the
queue formed is still pointing at a real, unresolved fault; counting it as a
false positive would understate precision for the wrong reason. Alerts before
onset are false under both rules.

**Containment** is the share of affected units flagged before **their own**
inspection timestamp — the only definition under which the flag could actually
have been acted on.

## Reproducing every number here

```bash
pip install -r requirements.txt
python -m eval.freeze_thresholds --verify     # confirm the config still matches
python -m eval.run_holdout                    # re-simulate, re-score, re-sweep
python -m eval.report                         # regenerate this file
```

The simulator is deterministic under its seed, so a clean checkout reproduces
these figures exactly. To rebuild from nothing, delete `runs/` first.
""")
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.report", description=__doc__)
    ap.add_argument("--rerun", action="store_true", help="re-score the holdout split first")
    ap.add_argument("--results", type=Path, default=RESULTS_PATH)
    ap.add_argument("--out", type=Path, default=REPORT_PATH)
    args = ap.parse_args(argv)

    if args.rerun or not args.results.exists():
        from .run_holdout import main as run_main
        code = run_main([])
        if code != 0:
            return code

    bundle = json.loads(args.results.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(bundle), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
