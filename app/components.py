"""Chart builders shared by the app's tabs.

Uninstrumented stations are rendered differently everywhere they appear: a hollow
diamond rather than a filled circle, and always with their uncertainty band drawn.
A station the twin cannot see must never read as a confident green.
"""

from __future__ import annotations

from typing import Any, Sequence

import plotly.graph_objects as go

# Chart template name. Registered by app.theme; defined here so the palette and
# the template identifier live together and theme.py can import both without a
# circular dependency.
PLOTLY_TEMPLATE = "ninja"

SEVERITY_SCALE = [
    (0.00, "#2f7d46"),   # healthy
    (0.35, "#8fbf3f"),
    (0.60, "#e8b62c"),
    (0.85, "#e2761f"),
    (1.00, "#c0392b"),   # critical
]
UNSEEN_OUTLINE = "#5b6b7a"
BAND_INSTRUMENTED = "#4A5A6E"   # uncertainty whiskers, directly measured
BAND_INFERRED = "#8296AF"       # deliberately brighter: the wider band is the point
MARKER_RING = "#2C3644"
AXIS_RULE = "#2C3644"

# Buffer pressure reuses the severity language: empty reads as background,
# filling as healthy green, and saturation as critical red.
PRESSURE_SCALE = [
    [0.00, "#12161D"], [0.20, "#1C3326"], [0.45, "#2f7d46"],
    [0.70, "#e8b62c"], [0.88, "#e2761f"], [1.00, "#c0392b"],
]


def severity_colour(severity: float, threshold: float) -> str:
    """Map an alert severity to a band colour, normalised by the live threshold."""
    if severity <= 0:
        return SEVERITY_SCALE[0][1]
    ratio = min(1.0, severity / max(threshold * 2.5, 1e-6))
    chosen = SEVERITY_SCALE[0][1]
    for cut, colour in SEVERITY_SCALE:
        if ratio >= cut:
            chosen = colour
    return chosen


def line_diagram(rows: Sequence[dict[str, Any]], threshold: float) -> go.Figure:
    """The 40-station line, coloured by live severity, with uncertainty bands."""
    fig = go.Figure()
    zones = {"body": (1, 15), "paint": (16, 24), "final_assembly": (25, 40)}
    for name, (lo, hi) in zones.items():
        fig.add_vrect(x0=lo - 0.5, x1=hi + 0.5, fillcolor="#8DA2BE", opacity=0.04,
                      line_width=0, annotation_text=name.replace("_", " "),
                      annotation_position="top left",
                      annotation_font={"size": 10.5, "color": "#6C7C90"})

    for instrumented in (True, False):
        subset = [r for r in rows if r["instrumented"] is instrumented]
        if not subset:
            continue
        fig.add_trace(go.Scatter(
            x=[r["station"] for r in subset],
            y=[r["deviation_pct"] for r in subset],
            mode="markers",
            name="instrumented" if instrumented else "uninstrumented (inferred)",
            marker={
                "size": [16 if instrumented else 18 for _ in subset],
                "symbol": "circle" if instrumented else "diamond-open",
                "color": [severity_colour(r["severity"], threshold) for r in subset],
                "line": {"width": 1.5 if instrumented else 2.5,
                         "color": [MARKER_RING if instrumented else UNSEEN_OUTLINE
                                   for _ in subset]},
            },
            error_y={
                "type": "data",
                "array": [100.0 * r["cycle_band_s"] / r["nominal_cycle_s"] for r in subset],
                "visible": True,
                "color": BAND_INFERRED if not instrumented else BAND_INSTRUMENTED,
                "thickness": 2.5 if not instrumented else 1.1,
                "width": 5 if not instrumented else 3,
            },
            customdata=[[r["name"], r["cycle_estimate_s"], r["nominal_cycle_s"],
                         r["cycle_band_s"], r["estimate_basis"], r["confidence"],
                         r["buffer_level"], r["buffer_capacity"], r["buffer_basis"],
                         r["severity"], r["l2_cause_count"]] for r in subset],
            hovertemplate=(
                "<b>S%{x} %{customdata[0]}</b><br>"
                "cycle estimate: %{customdata[1]:.1f}s ± %{customdata[3]:.1f}s "
                "(nominal %{customdata[2]:.1f}s)<br>"
                "basis: %{customdata[4]} · confidence %{customdata[5]:.2f}<br>"
                "buffer: %{customdata[6]}/%{customdata[7]} (%{customdata[8]})<br>"
                "L1 severity %{customdata[9]:.2f} · blamed by %{customdata[10]} L2 prediction(s)"
                "<extra></extra>"
            ),
        ))

    fig.add_hline(y=0, line_dash="dot", line_color=AXIS_RULE)
    fig.update_layout(
        height=390, template=PLOTLY_TEMPLATE,
        xaxis={"title": "station", "dtick": 2, "range": [0.2, 40.8]},
        yaxis={"title": "cycle time vs nominal (%)"},
        legend={"orientation": "h", "y": 1.12},
        margin={"l": 50, "r": 20, "t": 50, "b": 40},
    )
    return fig


def buffer_heatmap(timeline: Sequence[dict[str, Any]], station_ids: Sequence[int],
                   uninstrumented: Sequence[int]) -> go.Figure:
    """Inferred buffer pressure over the run. Buffer levels are never measured."""
    if not timeline:
        return go.Figure()
    step = max(1, len(timeline) // 240)
    frames = timeline[::step]
    z = [[snap["stations"][i]["buffer_pressure"] for snap in frames]
         for i in range(len(station_ids))]
    labels = [f"S{sid}{' ◇' if sid in uninstrumented else ''}" for sid in station_ids]
    fig = go.Figure(go.Heatmap(
        z=z, x=[round(s["ts"] / 3600.0, 2) for s in frames], y=labels,
        colorscale=PRESSURE_SCALE, zmin=0.0, zmax=1.0,
        colorbar={"title": {"text": "fill", "font": {"size": 11}},
                  "thickness": 10, "outlinewidth": 0, "tickfont": {"size": 10}},
        hovertemplate="%{y} at %{x:.1f} h<br>inferred fill %{z:.0%}<extra></extra>",
    ))
    fig.update_layout(height=620, template=PLOTLY_TEMPLATE,
                      xaxis_title="hours into the run",
                      yaxis_title="input buffer (◇ = inferred, station unseen)",
                      margin={"l": 70, "r": 20, "t": 30, "b": 40})
    return fig


def degradation_trends(timeline: Sequence[dict[str, Any]], station_ids: Sequence[int],
                       selected: Sequence[int], nominal: dict[int, float]) -> go.Figure:
    """Cycle-time estimate over time for the chosen stations."""
    fig = go.Figure()
    index = {sid: i for i, sid in enumerate(station_ids)}
    hours = [s["ts"] / 3600.0 for s in timeline]
    for sid in selected:
        i = index[sid]
        values = [snap["stations"][i]["cycle_estimate_s"] for snap in timeline]
        basis = timeline[-1]["stations"][i]["basis"] if timeline else "direct"
        fig.add_trace(go.Scatter(
            x=hours, y=values, mode="lines", name=f"S{sid} ({basis})",
            line={"dash": "dot" if basis == "inferred" else "solid", "width": 2},
        ))
        fig.add_hline(y=nominal[sid], line_dash="dash", line_width=1,
                      line_color=AXIS_RULE)
    fig.update_layout(height=380, template=PLOTLY_TEMPLATE,
                      xaxis_title="hours into the run",
                      yaxis_title="estimated cycle time (s)",
                      legend={"orientation": "h", "y": -0.22},
                      margin={"l": 50, "r": 20, "t": 30, "b": 40})
    return fig


def defect_pareto(counts: Sequence[tuple[int, int]], uninstrumented: Sequence[int]) -> go.Figure:
    """Where the twin thinks escapes are coming from, ranked."""
    if not counts:
        return go.Figure()
    labels = [f"S{sid}{' ◇' if sid in uninstrumented else ''}" for sid, _ in counts]
    values = [n for _, n in counts]
    total = sum(values) or 1
    cumulative, running = [], 0
    for v in values:
        running += v
        cumulative.append(100.0 * running / total)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=values, name="flagged units",
                         marker_color="#c0392b"))
    fig.add_trace(go.Scatter(x=labels, y=cumulative, name="cumulative %",
                             yaxis="y2", mode="lines+markers", line_color="#8D9AAB"))
    fig.update_layout(
        height=360, template=PLOTLY_TEMPLATE, xaxis_title="suspect station",
        yaxis={"title": "units flagged"},
        yaxis2={"title": "cumulative %", "overlaying": "y", "side": "right",
                "range": [0, 105]},
        legend={"orientation": "h", "y": 1.15},
        margin={"l": 50, "r": 50, "t": 40, "b": 40},
    )
    return fig


def sweep_curve(rows: Sequence[dict[str, Any]]) -> go.Figure:
    """Precision / recall / containment against false alarms, over sensitivity."""
    x = [r["sensitivity"] for r in rows]
    fig = go.Figure()
    for key, name in (("precision", "precision"), ("recall", "recall"),
                      ("mean_containment_rate", "containment")):
        fig.add_trace(go.Scatter(x=x, y=[r[key] for r in rows], name=name,
                                 mode="lines+markers"))
    fig.add_trace(go.Scatter(x=x, y=[r["false_alarms_per_shift"] for r in rows],
                             name="false alarms/shift", yaxis="y2",
                             mode="lines+markers", line={"dash": "dot"}))
    fig.add_trace(go.Scatter(x=x, y=[r["median_lead_time_min"] for r in rows],
                             name="median lead time (min)", yaxis="y2",
                             mode="lines+markers", line={"dash": "dash"}))
    fig.update_layout(
        height=430, template=PLOTLY_TEMPLATE, xaxis_title="master sensitivity",
        yaxis={"title": "rate in [0,1]", "range": [0, 1.05]},
        yaxis2={"title": "alerts/shift · minutes", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": -0.25},
        margin={"l": 50, "r": 50, "t": 30, "b": 60},
    )
    return fig
