"use client";

import { useMemo, useState } from "react";
import type { LineModel, StationState } from "@/lib/types";
import { confidenceLabel, severityColour } from "@/lib/format";

/**
 * The 40-station line.
 *
 * Deliberately static. This is data the operator is reading, not decoration, and
 * the `animate` skill is explicit that data must not move for style. Stations
 * update in place; when motion lands, only the specific station whose state just
 * changed gets a brief transition, and the diagram as a whole never animates.
 *
 * Uninstrumented stations are hollow diamonds with a visibly wider uncertainty
 * whisker. That difference is the whole point of the view: a station the twin
 * cannot see must never read as a confident green.
 */

const W = 1180;
const H = 320;
const PAD = { top: 34, right: 24, bottom: 42, left: 56 };
const Y_RANGE = 26; // percent deviation shown above and below nominal

interface Props {
  line: LineModel;
  stations: StationState[];
  severityByStation: Map<number, number>;
  causeCounts: Map<number, number>;
  threshold: number;
}

export function LineDiagram({
  line,
  stations,
  severityByStation,
  causeCounts,
  threshold,
}: Props) {
  const [hovered, setHovered] = useState<number | null>(null);

  const specs = useMemo(
    () => new Map(line.stations.map((s) => [s.id, s])),
    [line.stations],
  );

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (id: number) => PAD.left + ((id - 0.5) / line.n_stations) * plotW;
  const y = (pct: number) =>
    PAD.top + plotH / 2 - (Math.max(-Y_RANGE, Math.min(Y_RANGE, pct)) / Y_RANGE) * (plotH / 2);

  const rows = stations.map((state) => {
    const spec = specs.get(state.station)!;
    const estimate = state.cycle_estimate_s ?? spec.nominal_cycle_s;
    const deviation = (100 * (estimate - spec.nominal_cycle_s)) / spec.nominal_cycle_s;
    const band = (100 * state.cycle_band_s) / spec.nominal_cycle_s;
    return { state, spec, estimate, deviation, band };
  });

  const active = hovered === null ? null : rows.find((r) => r.state.station === hovered) ?? null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto"
        role="img"
        aria-label={
          `Cycle time versus nominal for all ${line.n_stations} stations. ` +
          `${line.instrumented_ids.length} are instrumented and drawn as filled circles. ` +
          `${line.uninstrumented_ids.length} have no sensors, are drawn as hollow diamonds, ` +
          `and carry a wider uncertainty band because their cycle time is inferred.`
        }
      >
        {/* zone bands */}
        {Object.entries(line.zones).map(([name, [lo, hi]]) => (
          <g key={name}>
            <rect
              x={x(lo) - plotW / line.n_stations / 2}
              y={PAD.top}
              width={((hi - lo + 1) / line.n_stations) * plotW}
              height={plotH}
              fill="#8DA2BE"
              opacity={0.04}
            />
            <text
              x={x(lo) - plotW / line.n_stations / 2 + 8}
              y={PAD.top - 12}
              fontSize={10.5}
              fill="var(--nj-mute)"
            >
              {name.replace(/_/g, " ")}
            </text>
          </g>
        ))}

        {/* gridlines */}
        {[-20, -10, 0, 10, 20].map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke={tick === 0 ? "var(--nj-border-strong)" : "var(--nj-grid)"}
              strokeDasharray={tick === 0 ? "3 3" : undefined}
            />
            <text
              x={PAD.left - 10}
              y={y(tick) + 4}
              fontSize={10.5}
              fill="var(--nj-mute)"
              textAnchor="end"
              className="tnum"
            >
              {tick}
            </text>
          </g>
        ))}
        <text
          transform={`translate(16 ${PAD.top + plotH / 2}) rotate(-90)`}
          fontSize={11}
          fill="var(--nj-dim)"
          textAnchor="middle"
        >
          cycle time vs nominal (%)
        </text>

        {rows.map(({ state, spec, deviation, band }) => {
          const cx = x(state.station);
          const cy = y(deviation);
          const colour = severityColour(severityByStation.get(state.station) ?? 0, threshold);
          const isHovered = hovered === state.station;
          return (
            <g
              key={state.station}
              onMouseEnter={() => setHovered(state.station)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(state.station)}
              onBlur={() => setHovered(null)}
              tabIndex={0}
              role="button"
              aria-label={`Station ${state.station}, ${spec.name}`}
              className="cursor-pointer outline-none"
            >
              {/* generous invisible hit area */}
              <rect
                x={cx - plotW / line.n_stations / 2}
                y={PAD.top}
                width={plotW / line.n_stations}
                height={plotH}
                fill="transparent"
              />
              {/* uncertainty whisker */}
              <line
                x1={cx}
                x2={cx}
                y1={y(deviation + band)}
                y2={y(deviation - band)}
                stroke={spec.instrumented ? "var(--nj-band-direct)" : "var(--nj-band-inferred)"}
                strokeWidth={spec.instrumented ? 1.1 : 2.4}
              />
              <line
                x1={cx - (spec.instrumented ? 3 : 5)}
                x2={cx + (spec.instrumented ? 3 : 5)}
                y1={y(deviation + band)}
                y2={y(deviation + band)}
                stroke={spec.instrumented ? "var(--nj-band-direct)" : "var(--nj-band-inferred)"}
                strokeWidth={spec.instrumented ? 1.1 : 2.4}
              />
              <line
                x1={cx - (spec.instrumented ? 3 : 5)}
                x2={cx + (spec.instrumented ? 3 : 5)}
                y1={y(deviation - band)}
                y2={y(deviation - band)}
                stroke={spec.instrumented ? "var(--nj-band-direct)" : "var(--nj-band-inferred)"}
                strokeWidth={spec.instrumented ? 1.1 : 2.4}
              />

              {spec.instrumented ? (
                <circle
                  cx={cx}
                  cy={cy}
                  r={isHovered ? 9 : 7.5}
                  fill={colour}
                  stroke={isHovered ? "var(--nj-text)" : "var(--nj-border-strong)"}
                  strokeWidth={1.5}
                />
              ) : (
                <rect
                  x={cx - 8}
                  y={cy - 8}
                  width={16}
                  height={16}
                  transform={`rotate(45 ${cx} ${cy})`}
                  fill="none"
                  stroke={isHovered ? "var(--nj-text)" : colour}
                  strokeWidth={2.5}
                />
              )}
            </g>
          );
        })}

        {/* x axis */}
        {Array.from({ length: line.n_stations / 2 }, (_, i) => (i + 1) * 2).map((id) => (
          <text
            key={id}
            x={x(id)}
            y={H - PAD.bottom + 18}
            fontSize={10}
            fill="var(--nj-mute)"
            textAnchor="middle"
            className="tnum"
          >
            {id}
          </text>
        ))}
        <text
          x={PAD.left + plotW / 2}
          y={H - 6}
          fontSize={11}
          fill="var(--nj-dim)"
          textAnchor="middle"
        >
          station
        </text>
      </svg>

      {active && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-line-strong bg-elev px-3 py-2 text-xs shadow-xl"
          style={{
            left: `${(x(active.state.station) / W) * 100}%`,
            top: 8,
            transform: "translateX(-50%)",
            minWidth: 230,
          }}
        >
          <div className="font-medium text-fg">
            S{active.state.station} · {active.spec.name}
          </div>
          <dl className="mt-1.5 space-y-0.5 text-mute">
            <div className="flex justify-between gap-4">
              <dt>cycle estimate</dt>
              <dd className="tnum text-dim">
                {active.estimate.toFixed(1)}s ± {active.state.cycle_band_s.toFixed(1)}s
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>nominal</dt>
              <dd className="tnum text-dim">{active.spec.nominal_cycle_s.toFixed(1)}s</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>basis</dt>
              <dd className="text-dim">
                {active.state.estimate_basis} · {confidenceLabel(active.state.confidence)}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt>buffer</dt>
              <dd className="tnum text-dim">
                {active.state.buffer_level ?? "?"}/{active.state.buffer_capacity} (
                {active.state.buffer_basis})
              </dd>
            </div>
            {(causeCounts.get(active.state.station) ?? 0) > 0 && (
              <div className="flex justify-between gap-4">
                <dt>blamed by</dt>
                <dd className="tnum text-dim">
                  {causeCounts.get(active.state.station)} prediction(s)
                </dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
