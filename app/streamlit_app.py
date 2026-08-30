"""Ninja operator console.

    streamlit run app/streamlit_app.py

Four views over one live twin. Every tab reads the same twin state produced by
running the twin against the selected run's event stream; the sensitivity slider
re-thresholds those cached candidates in place, exactly as the evaluation
harness does. Nothing on any tab is mocked or replayed.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import components as C  # noqa: E402
from app import state as S  # noqa: E402
from app import theme  # noqa: E402

st.set_page_config(page_title="Ninja", page_icon="◧", layout="wide",
                   initial_sidebar_state="expanded")
theme.apply()


# --------------------------------------------------------------------- sidebar

def sidebar():
    with st.sidebar:
        theme.brand()
    st.sidebar.caption("Digital twin of a 40-station mixed-model assembly line")

    scenarios = S.available_scenarios()
    labels = {f"[{s.split}] {s.scenario_id}": s for s in scenarios}
    default = next((k for k in labels if "tuning_drift_s12" in k), list(labels)[0])
    picked = st.sidebar.selectbox("Run", list(labels), index=list(labels).index(default))
    scenario = labels[picked]

    st.sidebar.divider()
    sensitivity = st.sidebar.slider(
        "Master sensitivity", 0.0, 1.0, 0.5, 0.05,
        help="Scales every alert threshold at once. Higher = more alerts. "
             "Re-thresholds the twin's cached candidates live; it does not re-run the twin.",
    )
    cfg = S.get_twin_config()
    st.sidebar.caption(
        f"L1 severity ≥ {cfg.l1_threshold(sensitivity):.2f} · "
        f"L2 confidence ≥ {cfg.l2_threshold(sensitivity):.2f} · "
        f"L3 risk ≥ {cfg.l3_threshold(sensitivity):.2f}"
    )

    fa = S.false_alarms_per_shift(sensitivity)
    if fa["mean"] is not None:
        ci = "" if fa["low"] is None else f"  (95% CI {fa['low']:.2f}–{fa['high']:.2f})"
        st.sidebar.metric("Expected false alarms / shift", f"{fa['mean']:.2f}",
                          help="Measured on control runs with no fault injected, where "
                               "every alert is false by definition. Updates with the slider.")
        st.sidebar.caption(f"from {fa['n']} tuning control run(s){ci} · shift = 7.5 h")

    st.sidebar.divider()
    line = S.get_line()
    st.sidebar.caption(
        f"{line.n_stations} stations · {len(line.instrumented_ids)} instrumented "
        f"({len(line.instrumented_ids) / line.n_stations:.0%}) · takt {line.takt_time_s:.0f}s\n\n"
        f"Unseen stations: {', '.join(str(s) for s in line.uninstrumented_ids)}"
    )
    st.sidebar.caption("All data is simulated. Ground truth exists only so the twin can "
                       "be validated honestly; the twin never reads it.")
    return scenario, sensitivity


# ------------------------------------------------------------------ supervisor

def tab_supervisor(run: S.LoadedRun, sensitivity: float):
    cfg = S.get_twin_config()
    rows = S.station_rows(run, sensitivity)
    alerts = S.alerts_for(run, sensitivity)
    ranked = S.grouped_alerts(run, sensitivity)

    unseen_degraded = [r for r in rows if not r["instrumented"] and r["deviation_pct"] > 5]
    off_nominal = [r for r in rows if abs(r["deviation_pct"]) > 5]
    at_risk = {a["vin"] for a in alerts["l3"]}
    n_alerts = len(alerts["l1"]) + len(alerts["l2"])
    worst = max((r["severity"] for r in rows), default=0.0)

    threshold = cfg.l1_threshold(sensitivity)
    severity_tone = ["healthy", "caution", "warning", "elevated", "critical"][
        min(4, sum(1 for cut, _ in C.SEVERITY_SCALE[1:]
                   if worst / max(threshold * 2.5, 1e-6) >= cut))]

    theme.metric_cards([
        {"label": "Live alerts", "value": n_alerts,
         "sub": f"{len(alerts['l1'])} drift · {len(alerts['l2'])} predicted",
         "tone": severity_tone if n_alerts else None},
        {"label": "At-risk units", "value": len(at_risk),
         "sub": "flagged before final inspection",
         "tone": "critical" if at_risk else None},
        {"label": "Stations off nominal", "value": len(off_nominal),
         "sub": f"of {len(rows)} on the line",
         "tone": "warning" if off_nominal else None},
        {"label": "Unseen stations degrading", "value": len(unseen_degraded),
         "sub": "inferred, no sensors",
         "tone": "unseen" if unseen_degraded else None},
    ])

    st.subheader("Line state")
    st.caption("Marker colour is live severity. **Hollow diamonds are uninstrumented "
               "stations** — they emit nothing per unit, so their cycle time is inferred "
               "from neighbouring timing and drawn with its (wider) uncertainty band.")
    st.plotly_chart(C.line_diagram(rows, cfg.l1_threshold(sensitivity)),
                    use_container_width=True)

    st.subheader("Alert feed")
    st.caption("One row per issue, ranked by severity × confidence. A live fault "
               "re-alerts until it is addressed; the repeat count shows how often. "
               "Expand any row for the numbers behind it.")
    if not ranked:
        st.success("No alerts above the current sensitivity threshold.")
        return

    for i, alert in enumerate(ranked[:20]):
        station = alert.get("station")
        signal = alert.get("signal") or alert.get("kind")
        conf = alert.get("confidence_label", "?")
        badge = "◇ inferred" if alert.get("basis") == "inferred" else "● measured"
        repeats = alert["repeat_count"]
        title = (f"{alert['layer']} · station {station} · {signal} · "
                 f"first raised t={alert['first_ts'] / 60:.0f} min · "
                 f"confidence {conf} · {badge}")
        if repeats > 1:
            title += (f" · re-fired {repeats}× through "
                      f"t={alert['last_ts'] / 60:.0f} min")
        if alert["layer"] == "L2":
            title += f" · predicts {alert['kind']} at station {alert['station']}"
        with st.expander(title):
            left, right = st.columns([3, 1])
            with left:
                if alert["layer"] == "L2":
                    st.write(f"Predicts **{alert['kind']}** at station "
                             f"**{alert['station']}**, caused by station "
                             f"**{alert['cause_station']}**.")
                st.json(alert["evidence"], expanded=True)
            with right:
                st.caption("Supervisor decision")
                key = f"{run.run_id}-{i}"
                if st.button("Accept", key=f"acc-{key}", use_container_width=True):
                    S.log_override(run, alert, "accept")
                    st.success("Logged.")
                if st.button("Override", key=f"ovr-{key}", use_container_width=True):
                    S.log_override(run, alert, "override")
                    st.info("Logged.")
                st.caption(f"→ {S.overrides_path(run).name}")


# ---------------------------------------------------------------- plant manager

def tab_plant(run: S.LoadedRun, sensitivity: float):
    line = S.get_line()
    rows = S.station_rows(run, sensitivity)
    alerts = S.alerts_for(run, sensitivity)
    timeline = run.twin_output["timeline"]
    unseen = set(line.uninstrumented_ids)

    st.subheader("Station degradation")
    worst = sorted(rows, key=lambda r: -abs(r["deviation_pct"]))[:5]
    default = [r["station"] for r in worst[:3]]
    picked = st.multiselect("Stations", line.station_ids, default=default,
                            format_func=lambda s: f"S{s}{' ◇' if s in unseen else ''}")
    if picked:
        st.plotly_chart(
            C.degradation_trends(timeline, line.station_ids, picked,
                                 {s: line.station(s).mean_cycle_s for s in line.station_ids}),
            use_container_width=True)
        st.caption("Dotted lines are inferred estimates for stations with no sensors; "
                   "dashed horizontals are each station's nominal cycle time.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Buffer pressure")
        st.caption("Buffer levels are never emitted by the line. These are inferred "
                   "from flow conservation across instrumented stations; rows marked ◇ "
                   "sit inside an unseen segment and carry a wider band.")
        st.plotly_chart(C.buffer_heatmap(timeline, line.station_ids, sorted(unseen)),
                        use_container_width=True)
    with right:
        st.subheader("Defect source Pareto")
        counts = collections.Counter()
        for a in alerts["l3"]:
            counts[a["suspect_station"]] += 1
        top = counts.most_common(10)
        if top:
            st.plotly_chart(C.defect_pareto(top, sorted(unseen)), use_container_width=True)
            st.caption("Suspect station for each at-risk unit, from L3's quality-signal "
                       "deviation scoring.")
        else:
            st.info("No units flagged at this sensitivity.")

        st.subheader("Supervisor overrides")
        rate = S.override_rate(run)
        if rate["total"]:
            c1, c2, c3 = st.columns(3)
            c1.metric("Accepted", rate["accepted"])
            c2.metric("Overridden", rate["overridden"])
            c3.metric("Override rate", f"{rate['override_rate']:.0%}")
            st.caption(f"Logged to `{S.overrides_path(run).relative_to(REPO_ROOT)}`")
        else:
            st.info("No supervisor decisions logged for this run yet. "
                    "Accept or override an alert on the Supervisor tab.")

    lift = run.twin_output["l3_summary"]["station_lift"]
    if lift:
        st.subheader("Which stations' signals actually predict escapes")
        st.caption("Learned from inspection outcomes as they arrived: mean |z| among "
                   "units that failed final inspection minus mean |z| among units that passed.")
        st.dataframe(lift, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ validation

def tab_validation(sensitivity: float):
    st.subheader("Sealed holdout report")
    report = S.holdout_report_text()
    if report:
        with st.expander("Full holdout report", expanded=False):
            st.markdown(report)
    else:
        st.warning("No holdout report yet. Run `python -m eval.run_holdout` "
                   "then `python -m eval.report`.")

    rows = S.sweep_rows()
    if rows:
        st.subheader("Threshold sweep")
        st.caption("From the sealed holdout scenarios. The marker shows where the "
                   "sidebar's sensitivity slider currently sits.")
        fig = C.sweep_curve(rows)
        fig.add_vline(x=sensitivity, line_dash="dot", line_color="#c0392b",
                      annotation_text=f"live: {sensitivity:.2f}")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Live perturbation")
    st.caption(f"Injects a fault into a **fresh simulation**, runs its same-seed "
               f"counterfactual, feeds only the event stream to the twin, and scores the "
               f"result with the same matching rule as the holdout report. Nothing is "
               f"canned. Horizon is shortened to "
               f"{S.PERTURBATION_HORIZON_S / 3600:.0f} h so this returns quickly.")

    line = S.get_line()
    unseen = set(line.uninstrumented_ids)
    c1, c2, c3, c4 = st.columns(4)
    family = c1.selectbox("Fault family", ["drift", "slowdown", "quality"])
    # Default to an uninstrumented station: it is the hardest case the twin
    # handles, so it is the one worth putting in front of someone first.
    default_station = line.uninstrumented_ids[-4] if len(line.uninstrumented_ids) >= 4 else 12
    station = c2.selectbox(
        "Target station", line.station_ids, index=line.station_ids.index(default_station),
        format_func=lambda s: f"S{s} — {line.station(s).name}"
                              f"{'  ◇ UNINSTRUMENTED' if s in unseen else ''}")
    severity = c3.slider("Severity", 5, 60, 30, 5,
                         help="drift: % cycle-time increase · quality: % failure "
                              "probability · slowdown: scales the slowdown frequency")
    onset_min = c4.slider("Onset (min)", 120, 300, int(S.PERTURBATION_ONSET_S / 60), 15)

    if station in unseen:
        st.info(f"Station {station} is **uninstrumented** — it emits no per-unit events. "
                "The twin must infer it from neighbouring station timing, and any alert "
                "will carry reduced confidence and a wider band.")

    if st.button("Run scenario", type="primary"):
        with st.spinner("Simulating, running the counterfactual, and scoring ..."):
            result = S.run_perturbation(family, station, float(severity),
                                        float(onset_min * 60), seed=1777)
        gt, sc = result["ground_truth"], result["score"]
        m = st.columns(4)
        m[0].metric("Detected", "yes" if sc.detected else "no")
        if sc.lead_time_queue_min is not None:
            m[1].metric("Lead time", f"{sc.lead_time_queue_min:+.0f} min",
                        help="Before the fault-attributable queue formed. Positive = early.")
        elif sc.detection_vs_onset_min is not None:
            m[1].metric("Detection vs onset", f"{sc.detection_vs_onset_min:+.0f} min",
                        help="No queue formed, so this is detection latency against onset.")
        else:
            m[1].metric("Lead time", "–")
        m[2].metric("Containment",
                    f"{sc.containment_rate:.0%}" if sc.containment_rate is not None else "–")
        m[3].metric("Units lost", gt["throughput_loss_units"])

        if gt["queue_forming"]:
            st.write(f"Ground truth: buffer **{gt['queue_formation_buffer']}** saturated at "
                     f"**{gt['queue_formation_ts'] / 60:.0f} min** (fault-attributable vs the "
                     f"same-seed counterfactual).")
        else:
            st.write("Ground truth: this fault never formed a queue, so it is scored "
                     "against onset instead and reported in its own column.")

        alerts = result["alerts"]
        st.write(f"Twin raised **{len(alerts['l1'])}** L1, **{len(alerts['l2'])}** L2 and "
                 f"**{len(alerts['l3'])}** L3 alerts.")
        first = [a for a in alerts["l1"] + alerts["l2"]
                 if abs((a.get("cause_station") if a["layer"] == "L2" else a["station"])
                        - station) <= 1]
        if first:
            earliest = min(first, key=lambda a: a["ts"])
            st.write(f"First correct alert at **{earliest['ts'] / 60:.0f} min** "
                     f"({earliest['layer']} / "
                     f"{earliest.get('signal') or earliest.get('kind')}, "
                     f"confidence {earliest.get('confidence_label')}):")
            st.json(earliest["evidence"])
        else:
            st.warning("No alert named this station or an immediate neighbour.")


# ------------------------------------------------------------------------ main

def main():
    scenario, sensitivity = sidebar()
    with st.spinner(f"Loading {scenario.scenario_id} (simulate → twin) ..."):
        run = S.load_run(scenario)

    gt = run.ground_truth
    chips = [f"{gt['fault']['family']} fault", f"{gt['horizon_s'] / 3600:.1f} h simulated",
             f"{run.split} split"]
    if gt["target_station"]:
        seen = "no sensors" if gt["target_station_instrumented"] is False else "instrumented"
        chips.insert(1, f"station {gt['target_station']} · {seen}")
    theme.page_title(run.scenario_id, chips)

    supervisor, plant, validation = st.tabs(
        ["Supervisor", "Plant manager", "Validation"])
    with supervisor:
        tab_supervisor(run, sensitivity)
    with plant:
        tab_plant(run, sensitivity)
    with validation:
        tab_validation(sensitivity)


main()
