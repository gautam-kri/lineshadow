"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { LineModel, RunPayload } from "@/lib/types";
import { fmtSigned, minutes } from "@/lib/format";

/**
 * Inject a fault into a fresh simulation, live.
 *
 * Nothing here is canned: the request runs a new simulation, its same-seed
 * counterfactual, feeds only the event stream to the twin, and scores the result
 * with the same matching rule as the holdout report.
 *
 * MOTION (not yet implemented): the pending state gets an indeterminate pulse --
 * indeterminate is the honest choice because the server timing is genuinely
 * unknown, and a fake progress bar would claim knowledge we do not have. The
 * result card enters only once data has actually arrived; never before.
 */

interface Props {
  line: LineModel;
  /** Defaults to an uninstrumented station: the hardest case the twin handles. */
  defaultStation?: number;
}

type Family = "drift" | "slowdown" | "quality";

export function PerturbationPanel({ line, defaultStation }: Props) {
  const fallback = line.uninstrumented_ids.at(-4) ?? line.uninstrumented_ids[0] ?? 12;
  const [family, setFamily] = useState<Family>("drift");
  const [station, setStation] = useState(defaultStation ?? fallback);
  const [severity, setSeverity] = useState(30);
  const [onsetMin, setOnsetMin] = useState(210);

  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<RunPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const spec = line.stations.find((s) => s.id === station);
  const unseen = spec ? !spec.instrumented : false;

  async function run() {
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const payload = await api.perturb({
        family,
        station,
        severity_pct: severity,
        onset_s: onsetMin * 60,
      });
      setResult(payload);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="rounded-xl border border-line bg-elev p-5">
      <h2 className="nj-label">Live perturbation</h2>
      <p className="mt-2 max-w-3xl text-[0.82rem] leading-relaxed text-mute">
        Injects a fault into a <strong className="text-dim">fresh simulation</strong>, runs its
        same-seed counterfactual, feeds only the event stream to the twin, and scores the result
        with the same matching rule as the holdout report. Nothing is canned. The horizon is
        shortened to 8 h so this returns quickly.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className="nj-label">Fault family</span>
          <select
            value={family}
            onChange={(e) => setFamily(e.target.value as Family)}
            className="mt-1.5 w-full rounded-lg border border-line bg-input px-2.5 py-2 text-sm text-fg"
          >
            <option value="drift">drift</option>
            <option value="slowdown">slowdown</option>
            <option value="quality">quality</option>
          </select>
        </label>

        <label className="block">
          <span className="nj-label">Target station</span>
          <select
            value={station}
            onChange={(e) => setStation(Number(e.target.value))}
            className="mt-1.5 w-full rounded-lg border border-line bg-input px-2.5 py-2 text-sm text-fg"
          >
            {line.stations.map((s) => (
              <option key={s.id} value={s.id}>
                S{s.id} — {s.name}
                {s.instrumented ? "" : "  ◇ UNINSTRUMENTED"}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="nj-label">Severity · {severity}</span>
          <input
            type="range"
            min={5}
            max={60}
            step={5}
            value={severity}
            onChange={(e) => setSeverity(Number(e.target.value))}
            className="mt-3 w-full"
          />
        </label>

        <label className="block">
          <span className="nj-label">Onset · {onsetMin} min</span>
          <input
            type="range"
            min={120}
            max={300}
            step={15}
            value={onsetMin}
            onChange={(e) => setOnsetMin(Number(e.target.value))}
            className="mt-3 w-full"
          />
        </label>
      </div>

      {unseen && (
        <p className="mt-4 rounded-lg border border-accent-dim bg-accent-dim/15 px-3.5 py-2.5 text-[0.82rem] text-dim">
          Station {station} is <strong className="text-fg">uninstrumented</strong> — it emits no
          per-unit events. The twin must infer it from neighbouring station timing, and any alert
          will carry reduced confidence and a wider band.
        </p>
      )}

      <button
        type="button"
        onClick={run}
        disabled={pending}
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-60"
      >
        {pending ? "Running simulation…" : "Run scenario"}
      </button>

      {error && (
        <p className="mt-4 rounded-lg border border-critical px-3.5 py-2.5 text-sm text-critical">
          {error}
        </p>
      )}

      {result && !pending && <PerturbationResult result={result} />}
    </section>
  );
}

function PerturbationResult({ result }: { result: RunPayload }) {
  const { score, ground_truth: gt } = result;
  const lead =
    score.lead_time_queue_min !== null
      ? { label: "Lead time", value: fmtSigned(score.lead_time_queue_min), hint: "before the queue formed" }
      : score.detection_vs_onset_min !== null
        ? { label: "Detection vs onset", value: fmtSigned(score.detection_vs_onset_min), hint: "no queue formed" }
        : { label: "Lead time", value: "–", hint: "" };

  return (
    <div className="mt-5 border-t border-line pt-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Figure label="Detected" value={score.detected ? "yes" : "no"} />
        <Figure label={lead.label} value={lead.value} hint={lead.hint} />
        <Figure
          label="Containment"
          value={score.containment_rate === null ? "–" : `${(score.containment_rate * 100).toFixed(0)}%`}
        />
        <Figure label="Units lost" value={String(score.throughput_loss_units)} />
      </div>

      <p className="mt-4 text-[0.82rem] text-mute">
        {gt.queue_forming ? (
          <>
            Ground truth: buffer <strong className="text-dim">{gt.queue_formation_buffer}</strong>{" "}
            saturated at{" "}
            <strong className="text-dim">
              {minutes(gt.queue_formation_ts ?? 0).toFixed(0)} min
            </strong>{" "}
            — fault-attributable versus the same-seed counterfactual.
          </>
        ) : (
          <>
            Ground truth: this fault never formed a queue, so it is scored against onset instead and
            reported in its own column.
          </>
        )}
      </p>
      <p className="mt-1.5 text-[0.82rem] text-mute">
        Twin raised <strong className="text-dim">{result.alerts.l1.length}</strong> L1,{" "}
        <strong className="text-dim">{result.alerts.l2.length}</strong> L2 and{" "}
        <strong className="text-dim">{result.alerts.l3.length}</strong> L3 alerts.
      </p>
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="nj-label">{label}</div>
      <div className="tnum mt-1 text-2xl font-semibold tracking-tight text-fg">{value}</div>
      {hint && <div className="mt-0.5 text-[0.7rem] text-mute">{hint}</div>}
    </div>
  );
}
