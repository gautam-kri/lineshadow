"use client";

import { useMemo, useState } from "react";
import type { StationAlert } from "@/lib/types";
import { groupAlerts, minutes } from "@/lib/format";

/**
 * Severity-ranked alert feed.
 *
 * One row per issue, not per alert: a real unaddressed fault re-alerts for hours,
 * which is correct detector behaviour and is what the evaluation scores, but it
 * makes a useless feed. The repeat count carries that information instead.
 *
 * MOTION (not yet implemented): alerts entering and leaving this list are
 * feedback at the occasional tier -- 200-300ms, ease-out, sliding in from the
 * direction of the line diagram, with a symmetric exit via AnimatePresence.
 * Left static until the motion skills can be loaded.
 */

interface Props {
  alerts: (StationAlert & { rank_score: number })[];
  limit?: number;
}

const signalOf = (alert: StationAlert) =>
  alert.layer === "L2" ? alert.kind : alert.signal;

export function AlertFeed({ alerts, limit = 20 }: Props) {
  const [open, setOpen] = useState<string | null>(null);

  const grouped = useMemo(
    () => groupAlerts(alerts, (a) => a.rank_score, signalOf).slice(0, limit),
    [alerts, limit],
  );

  if (grouped.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-elev px-4 py-3 text-sm text-dim">
        No alerts above the current sensitivity threshold.
      </p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {grouped.map((alert) => {
        const key = `${alert.layer}-${alert.station}-${signalOf(alert)}`;
        const isOpen = open === key;
        const inferred = alert.basis === "inferred";
        return (
          <li key={key} className="overflow-hidden rounded-lg border border-line bg-elev">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : key)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[0.82rem] text-dim hover:bg-hover"
            >
              <span
                className="rounded px-1.5 py-0.5 text-[0.66rem] font-semibold tracking-wider"
                style={{
                  color: alert.layer === "L1" ? "var(--nj-accent)" : "var(--nj-caution)",
                  border: "1px solid currentColor",
                }}
              >
                {alert.layer}
              </span>
              <span className="text-fg">station {alert.station}</span>
              <span className="text-mute">·</span>
              <span>{signalOf(alert)}</span>
              <span className="text-mute">·</span>
              <span className="tnum">first raised t={minutes(alert.firstTs).toFixed(0)} min</span>
              <span className="text-mute">·</span>
              <span title={inferred ? "inferred from neighbouring timing" : "directly measured"}>
                {inferred ? "◇ inferred" : "● measured"}
              </span>
              <span
                className="rounded px-1.5 py-0.5 text-[0.66rem] uppercase tracking-wider"
                style={{
                  color:
                    alert.confidence_label === "high"
                      ? "var(--nj-healthy)"
                      : alert.confidence_label === "medium"
                        ? "var(--nj-warning)"
                        : "var(--nj-unseen)",
                  border: "1px solid currentColor",
                }}
              >
                {alert.confidence_label}
              </span>
              {alert.repeatCount > 1 && (
                <span className="tnum text-mute">
                  re-fired {alert.repeatCount}× through t={minutes(alert.lastTs).toFixed(0)} min
                </span>
              )}
              <span className="ml-auto text-mute">{isOpen ? "−" : "+"}</span>
            </button>

            {isOpen && (
              <div className="border-t border-line px-3.5 py-3">
                {alert.layer === "L2" && (
                  <p className="mb-2 text-[0.82rem] text-dim">
                    Predicts <strong className="text-fg">{alert.kind}</strong> at station{" "}
                    <strong className="text-fg">{alert.station}</strong>, caused by station{" "}
                    <strong className="text-fg">{alert.cause_station}</strong>.
                  </p>
                )}
                {/* Evidence is mandatory on every alert; this is the audit trail
                    and it stays static and fully readable. */}
                <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-1 font-mono text-[0.73rem]">
                  {Object.entries(alert.evidence).map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-mute">{k}</dt>
                      <dd className="tnum text-dim">
                        {v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
