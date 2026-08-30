# Ninja — holdout validation report

> **Every figure below comes from sealed holdout scenarios that were never used
> for tuning.** Detector thresholds were calibrated exclusively against the
> *tuning* split's control runs and then frozen. `eval/run_holdout.py` refuses to
> produce this report unless the live `config/twin.yaml` still hashes to the
> frozen record, so no number here can have been produced by thresholds adjusted
> after seeing these scenarios.

| | |
|---|---|
| Generated | 2026-08-30T07:54:17+00:00 |
| Frozen config | `config/twin.frozen.yaml` |
| Frozen at | 2026-08-30T07:53:51+00:00 |
| Config SHA-256 | `6f499ddc6de4d4404fdd61739d8bf28006144334ad41b1779448049cdae3c0e8` |
| Holdout seed range | **9000–9999** (tuning uses 1000–1999; the ranges are disjoint and enforced at load time) |
| Master sensitivity | 0.5 |
| Line | 40 stations, 26 instrumented (65%), takt 76.0 s |
| Uninstrumented stations | 3, 5, 7, 11, 14, 17, 22, 25, 27, 29, 34, 36, 37, 39 |
| L3 calibrated model | loaded from `models/l3.joblib` — tuning split only (see scripts/train_l3.py leakage guard). L3's unsupervised path runs regardless; the model only sharpens it. |

> Freeze note: Rebrand to Ninja; comment text only, no threshold changed.

## Headline results

| Metric | Value |
|---|---|
| Faults detected (recall) | **6 / 6** |
| Alert precision | **74.2%** |
| Median lead time, queue-forming faults (n=4) | **+37.4 min early** |
| Lead-time range, queue-forming | +16.1 to +56.8 min |
| Median detection vs onset, non-queue-forming (n=2) | -12.0 min |
| Defect containment, quality faults (n=2) | **99.2%** (387 / 390 affected units) |
| Median containment head start | 25.0 min before the first escape surfaced |
| False alarms per shift (controls only, n=3) | **5.50** (95% CI 0.09–10.91) |
| Throughput lost to the injected faults | 128 units |

**Sign convention: positive lead time means the twin called it early.**

The two lead-time columns use different reference points and are never averaged
together. Queue-forming faults are scored against the timestamp at which a buffer
actually saturated because of the fault. Faults that never formed a queue have no
such reference, so they are scored against fault onset instead, which makes that
column a detection *latency* and therefore negative.

## Per-scenario results

| scenario | family | station | instrumented | queue formed | detected | lead vs queue (min) | detection vs onset (min) | containment | first alert | units lost |
|---|---|---|---|---|---|---|---|---|---|---|
| `holdout_drift_s19` | drift | 19 | yes | yes | yes | +41.2 | – | – | L1 / cycle_time | 39 |
| `holdout_drift_s34_uninstr` | drift | 34 | **no** | yes | yes | +33.7 | – | – | L1 / cycle_time_inferred | 47 |
| `holdout_drift_step_s26` | drift | 26 | yes | yes | yes | +56.8 | – | – | L1 / cycle_time | 25 |
| `holdout_quality_s06` | quality | 6 | yes | no | yes | – | -14.1 | 99% | L1 / torque | 0 |
| `holdout_quality_s21` | quality | 21 | yes | no | yes | – | -9.8 | 99% | L1 / torque | 0 |
| `holdout_slowdown_s12` | slowdown | 12 | yes | yes | yes | +16.1 | – | – | L1 / cycle_time | 17 |

### Faults at stations the twin cannot see directly

1 of 6 holdout faults were injected at an **uninstrumented** station,
which emits no per-unit events at all. Those were detected purely from the timing
of neighbouring instrumented stations plus flow conservation across the
intervening buffers, and every such alert is reported at reduced confidence with
a wider uncertainty band — the twin never renders a station it cannot see as green.


## Control scenarios (false-alarm measurement)

False alarms are measured **only** on control runs with no fault injected, where
every alert is false by construction. They are deliberately not derived from the
faulted runs: there, a correct alert that fires outside the scoring window cannot
be cleanly separated from a genuinely spurious one, so any false-alarm rate taken
from faulted runs would be measuring the scoring window rather than the detector.

One shift = 7.5 h. With n=3 control runs the interval is wide; it is
reported rather than hidden, and the lower bound is clamped at zero because a
rate cannot be negative.

| control scenario | alerts | shifts | alerts/shift |
|---|---|---|---|
| `holdout_control_a` | 13 | 2.0 | 6.50 |
| `holdout_control_b` | 14 | 2.0 | 7.00 |
| `holdout_control_c` | 6 | 2.0 | 3.00 |

## Threshold sweep

The twin runs once per scenario at the sensitivity-1 emission floor; each row
below is a re-threshold of those cached candidates, so all 12 points see an
identical candidate set. Alert selection is a score cut followed by a greedy
earliest-first minimum-gap thinning, and greedy earliest-first selection is
optimal for cardinality under a minimum-gap constraint — so a higher sensitivity
can never yield fewer alerts than a lower one. The monotonicity of the
false-alarm column is therefore structural, not empirical.

Full data: [`threshold_sweep.csv`](threshold_sweep.csv) · interactive plot: [`threshold_sweep.html`](threshold_sweep.html)

| sensitivity | L1 threshold | precision | recall | median lead (min) | containment | false alarms/shift | 95% CI |
|---|---|---|---|---|---|---|---|
| 0.00 | 3.00 | 86% | 100% | +36.2 | 79% | 1.17 | 0.00–4.29 |
| 0.09 | 2.82 | 84% | 100% | +36.2 | 87% | 1.50 | 0.00–5.23 |
| 0.18 | 2.64 | 84% | 100% | +36.7 | 91% | 2.33 | 0.00–7.50 |
| 0.27 | 2.45 | 83% | 100% | +36.7 | 94% | 2.33 | 0.00–7.50 |
| 0.36 | 2.27 | 80% | 100% | +36.7 | 97% | 3.33 | 0.00–8.93 |
| 0.45 | 2.09 | 77% | 100% | +37.4 | 99% | 4.33 | 0.00–9.93 |
| 0.55 | 1.91 | 71% | 100% | +37.4 | 100% | 6.50 | 1.09–11.91 |
| 0.64 | 1.73 | 56% | 100% | +37.4 | 100% | 13.00 | 0.39–25.61 |
| 0.73 | 1.55 | 51% | 100% | +39.7 | 100% | 18.00 | 4.91–31.09 |
| 0.82 | 1.36 | 44% | 100% | +39.7 | 100% | 24.67 | 8.46–40.88 |
| 0.91 | 1.18 | 35% | 100% | +41.6 | 100% | 40.33 | 18.63–62.04 |
| 1.00 | 1.00 | 19% | 100% | +57.2 | 100% | 109.17 | 79.35–138.99 |

## How these numbers are defined

**Ground truth by counterfactual.** Each scenario is simulated twice from the same
seed — once with the fault, once without — with per-unit random draws shared
between the two runs, so any difference between them is attributable to the fault
alone. `queue_formation_ts` is the first buffer saturation that occurs in the
faulted run for 5 consecutive units
that did *not* saturate that buffer in the counterfactual. Defining it as "any buffer reaching capacity" would
score the detector against noise, because buffers saturate during normal
operation too; requiring a sustained divergence also rejects the one-off flips
that chaotic trajectory divergence produces once two runs have drifted apart.

**Alert matching.** An alert is matched if it names the faulted station or an
immediate neighbour (tolerance ±1) *and* fires within
`[onset, queue_formation + 15 min]`, or within
`[onset, onset + 90 min]` for faults that never form a
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

