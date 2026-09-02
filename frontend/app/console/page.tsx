"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertFeed } from "@/components/console/AlertFeed";
import { FalseAlarmReadout } from "@/components/console/FalseAlarmReadout";
import { LineDiagram } from "@/components/console/LineDiagram";
import { PerturbationPanel } from "@/components/console/PerturbationPanel";
import { api, ApiError, isStatic } from "@/lib/api";
import type { HoldoutBundle, LineModel, RunPayload, ScenarioSummary } from "@/lib/types";
import { fmtHours, fmtSigned, severityColour } from "@/lib/format";

const DEFAULT_SCENARIO = "tuning_drift_s12";
/** The alert list needs the server; the counter does not. See `falseAlarmsAt`. */
const REFETCH_DEBOUNCE_MS = 180;

export default function ConsolePage() {
  const [line, setLine] = useState<LineModel | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [holdout, setHoldout] = useState<HoldoutBundle | null>(null);
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO);
  const [sensitivity, setSensitivity] = useState(0.5);
  const [run, setRun] = useState<RunPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Static data: fetched once.
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.line(controller.signal),
      api.scenarios(controller.signal),
      api.holdout(controller.signal).catch(() => null),
    ])
      .then(([lineModel, scenarioList, holdoutBundle]) => {
        setLine(lineModel);
        setScenarios(scenarioList);
        setHoldout(holdoutBundle);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof ApiError ? cause.message : String(cause));
        }
      });
    return () => controller.abort();
  }, []);

  // Run data: refetched on scenario change, and debounced on sensitivity drag so
  // the slider stays responsive while the server catches up.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    if (timer.current) clearTimeout(timer.current);
    setLoading(true);
    timer.current = setTimeout(() => {
      api
        .run(scenarioId, sensitivity, controller.signal)
        .then((payload) => {
          setRun(payload);
          setError(null);
        })
        .catch((cause) => {
          if (!controller.signal.aborted) {
            setError(cause instanceof ApiError ? cause.message : String(cause));
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, REFETCH_DEBOUNCE_MS);
    return () => {
      controller.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [scenarioId, sensitivity]);

  /**
   * False alarms per shift, read straight off the sealed holdout sweep and
   * interpolated between its twelve measured points. This updates in the same
   * frame as the slider because it needs no network round trip -- which is the
   * point: this is the live proof-of-tradeoff moment.
   */
  const falseAlarmsAt = useCallback(
    (value: number): number | null => {
      const rows = holdout?.sweep;
      if (!rows?.length) return null;
      const sorted = [...rows].sort((a, b) => a.sensitivity - b.sensitivity);
      if (value <= sorted[0].sensitivity) return sorted[0].false_alarms_per_shift;
      const last = sorted[sorted.length - 1];
      if (value >= last.sensitivity) return last.false_alarms_per_shift;
      for (let i = 1; i < sorted.length; i += 1) {
        const hi = sorted[i];
        const lo = sorted[i - 1];
        if (value <= hi.sensitivity) {
          const t = (value - lo.sensitivity) / (hi.sensitivity - lo.sensitivity);
          return (
            lo.false_alarms_per_shift +
            t * (hi.false_alarms_per_shift - lo.false_alarms_per_shift)
          );
        }
      }
      return last.false_alarms_per_shift;
    },
    [holdout],
  );

  const severityByStation = useMemo(() => {
    const map = new Map<number, number>();
    for (const alert of run?.alerts.l1 ?? []) {
      map.set(alert.station, Math.max(map.get(alert.station) ?? 0, alert.severity_score));
    }
    return map;
  }, [run]);

  const causeCounts = useMemo(() => {
    const map = new Map<number, number>();
    for (const alert of run?.alerts.l2 ?? []) {
      map.set(alert.cause_station, (map.get(alert.cause_station) ?? 0) + 1);
    }
    return map;
  }, [run]);

  if (error && !line) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-24">
        <h1 className="text-lg font-semibold text-fg">Engine not reachable</h1>
        <p className="mt-3 text-sm text-dim">{error}</p>
        <pre className="mt-4 overflow-x-auto rounded-lg border border-line bg-elev p-4 font-mono text-xs text-dim">
          uvicorn api.main:app --port 8000
        </pre>
      </main>
    );
  }

  if (!line) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-24 text-sm text-mute">Loading plant model…</main>
    );
  }

  const gt = run?.ground_truth;
  const unseenDegrading =
    run?.stations.filter((s) => {
      if (s.instrumented) return false;
      const spec = line.stations.find((x) => x.id === s.station);
      if (!spec || s.cycle_estimate_s === null) return false;
      return (100 * (s.cycle_estimate_s - spec.nominal_cycle_s)) / spec.nominal_cycle_s > 5;
    }).length ?? 0;
  const offNominal =
    run?.stations.filter((s) => {
      const spec = line.stations.find((x) => x.id === s.station);
      if (!spec || s.cycle_estimate_s === null) return false;
      return Math.abs((100 * (s.cycle_estimate_s - spec.nominal_cycle_s)) / spec.nominal_cycle_s) > 5;
    }).length ?? 0;
  const atRisk = new Set((run?.alerts.l3 ?? []).map((a) => a.vin)).size;
  const nAlerts = (run?.alerts.l1.length ?? 0) + (run?.alerts.l2.length ?? 0);
  const worst = Math.max(0, ...severityByStation.values());
  const fa = falseAlarmsAt(sensitivity);

  return (
    <main className="mx-auto w-full max-w-[1600px] px-6 py-6 lg:px-10">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg text-accent">◧</span>
            <span className="font-display text-lg font-semibold tracking-tight">Ninja</span>
            <span className="text-sm text-mute">operator console</span>
          </div>
          <p className="mt-1 text-[0.8rem] text-mute">
            Digital twin of a {line.n_stations}-station mixed-model assembly line ·{" "}
            {line.instrumented_ids.length} instrumented (
            {Math.round((line.instrumented_ids.length / line.n_stations) * 100)}%) · takt{" "}
            {line.takt_time_s.toFixed(0)}s
          </p>
        </div>
        <Link href="/" className="text-[0.8rem] text-accent hover:underline">
          ← overview
        </Link>
      </header>

      {isStatic && (
        <p className="mt-4 rounded-lg border border-accent-dim bg-accent-dim/15 px-4 py-2.5 text-[0.8rem] leading-relaxed text-dim">
          <strong className="text-fg">Hosted build.</strong> Everything here is real output from
          the engine, baked at the twelve measured sensitivity points of the published sweep — so
          the slider snaps to scored values rather than interpolating. The live perturbation panel
          at the bottom needs the Python engine and is disabled rather than replayed.
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-end gap-6">
        <label className="block min-w-64">
          <span className="nj-label">Run</span>
          <select
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            className="mt-1.5 w-full rounded-lg border border-line bg-input px-2.5 py-2 text-sm text-fg"
          >
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                [{s.split}] {s.scenario_id}
              </option>
            ))}
          </select>
        </label>

        <label className="block min-w-72 flex-1">
          <span className="nj-label">
            Master sensitivity ·{" "}
            <span className="tnum text-accent">{sensitivity.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={sensitivity}
            onChange={(e) => setSensitivity(Number(e.target.value))}
            className="mt-3 w-full"
            aria-label="Master sensitivity"
          />
          {run && (
            <span className="mt-1.5 block text-[0.72rem] text-mute">
              L1 ≥ {run.thresholds.l1.toFixed(2)} · L2 ≥ {run.thresholds.l2.toFixed(2)} · L3 ≥{" "}
              {run.thresholds.l3.toFixed(2)}
            </span>
          )}
        </label>

        <FalseAlarmReadout
          value={fa}
          caption="from the sealed holdout controls · shift = 7.5 h"
        />
      </div>

      {gt && (
        <div className="mt-5 flex flex-wrap items-center gap-2 text-[0.72rem]">
          <Chip>{gt.fault.family} fault</Chip>
          {gt.target_station && (
            <Chip>
              station {gt.target_station} ·{" "}
              {gt.target_station_instrumented === false ? "no sensors" : "instrumented"}
            </Chip>
          )}
          <Chip>{fmtHours(gt.horizon_s)} simulated</Chip>
          <Chip>{gt.split} split</Chip>
          {run?.score.detected && (
            <Chip>
              {run.score.lead_time_queue_min !== null
                ? `${fmtSigned(run.score.lead_time_queue_min)} before queue`
                : `${fmtSigned(run.score.detection_vs_onset_min)} vs onset`}
            </Chip>
          )}
        </div>
      )}

      <section className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card
          label="Live alerts"
          value={nAlerts}
          sub={`${run?.alerts.l1.length ?? 0} drift · ${run?.alerts.l2.length ?? 0} predicted`}
          tone={nAlerts ? severityColour(worst, run?.thresholds.l1 ?? 2) : undefined}
        />
        <Card
          label="At-risk units"
          value={atRisk}
          sub="flagged before final inspection"
          tone={atRisk ? "var(--nj-critical)" : undefined}
        />
        <Card
          label="Stations off nominal"
          value={offNominal}
          sub={`of ${line.n_stations} on the line`}
          tone={offNominal ? "var(--nj-warning)" : undefined}
        />
        <Card
          label="Unseen stations degrading"
          value={unseenDegrading}
          sub="inferred, no sensors"
          tone={unseenDegrading ? "var(--nj-unseen)" : undefined}
        />
      </section>

      <section className="mt-8">
        <h2 className="nj-label border-b border-line pb-2">Line state</h2>
        <p className="mt-2.5 max-w-4xl text-[0.82rem] leading-relaxed text-mute">
          Marker colour is live severity.{" "}
          <strong className="text-dim">Hollow diamonds are uninstrumented stations</strong> — they
          emit nothing per unit, so their cycle time is inferred from neighbouring timing and drawn
          with its wider uncertainty band.
        </p>
        <div className="mt-3 rounded-xl border border-line bg-elev p-2">
          {run ? (
            <LineDiagram
              line={line}
              stations={run.stations}
              severityByStation={severityByStation}
              causeCounts={causeCounts}
              threshold={run.thresholds.l1}
            />
          ) : (
            <div className="h-64 animate-pulse rounded-lg bg-hover" />
          )}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="nj-label border-b border-line pb-2">
          Alert feed {loading && <span className="ml-2 text-mute">updating…</span>}
        </h2>
        <p className="mt-2.5 max-w-4xl text-[0.82rem] leading-relaxed text-mute">
          One row per issue, ranked by severity × confidence. A live fault re-alerts until it is
          addressed; the repeat count shows how often. Expand any row for the numbers behind it.
        </p>
        <div className="mt-3">
          <AlertFeed alerts={run?.ranked_alerts ?? []} />
        </div>
      </section>

      <section className="mt-8">
        <PerturbationPanel line={line} />
      </section>

      <footer className="mt-10 border-t border-line pt-4 text-[0.75rem] leading-relaxed text-mute">
        All data is simulated. Ground truth exists only so the twin can be validated honestly; the
        twin never reads it. Figures shown against sealed holdout scenarios come from a frozen
        config.
      </footer>
    </main>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-line-strong px-2 py-0.5 text-dim">{children}</span>
  );
}

function Card({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number | string;
  sub: string;
  tone?: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-elev px-4 py-3">
      <span
        className="absolute inset-y-0 left-0 w-0.5"
        style={{ background: tone ?? "transparent" }}
        aria-hidden
      />
      <div className="nj-label">{label}</div>
      <div className="tnum mt-1 text-3xl font-semibold tracking-tight text-fg">{value}</div>
      <div className="mt-0.5 text-[0.72rem] text-mute">{sub}</div>
    </div>
  );
}
