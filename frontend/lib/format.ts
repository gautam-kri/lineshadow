import type { ConfidenceLabel } from "./types";

/**
 * Presentation helpers.
 *
 * All engine time is seconds; conversion to minutes and hours happens here and
 * only here, at the display boundary -- the same rule the Python side follows.
 */

export const SEVERITY_STOPS: [number, string][] = [
  [0.0, "var(--nj-healthy)"],
  [0.35, "var(--nj-caution)"],
  [0.6, "var(--nj-warning)"],
  [0.85, "var(--nj-elevated)"],
  [1.0, "var(--nj-critical)"],
];

/** Mirrors `severity_colour` in app/components.py, normalised by the live threshold. */
export function severityColour(severity: number, threshold: number): string {
  if (severity <= 0) return SEVERITY_STOPS[0][1];
  const ratio = Math.min(1, severity / Math.max(threshold * 2.5, 1e-6));
  let chosen = SEVERITY_STOPS[0][1];
  for (const [cut, colour] of SEVERITY_STOPS) if (ratio >= cut) chosen = colour;
  return chosen;
}

export function confidenceLabel(score: number): ConfidenceLabel {
  if (score >= 0.8) return "high";
  if (score >= 0.45) return "medium";
  return "low";
}

export const minutes = (seconds: number) => seconds / 60;

export function fmtMinutes(seconds: number, digits = 0): string {
  return `${minutes(seconds).toFixed(digits)} min`;
}

export function fmtHours(seconds: number, digits = 1): string {
  return `${(seconds / 3600).toFixed(digits)} h`;
}

/** Positive lead time means early. Always show the sign so that stays obvious. */
export function fmtSigned(value: number | null, digits = 0, unit = "min"): string {
  if (value === null || Number.isNaN(value)) return "–";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)} ${unit}`;
}

export function fmtPct(value: number | null, digits = 0): string {
  if (value === null || Number.isNaN(value)) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Collapse repeat alerts into one row per issue.
 *
 * A real, unaddressed fault re-alerts for hours -- correct detector behaviour,
 * and what the evaluation scores -- but a useless feed. Mirrors `grouped_alerts`
 * in app/state.py.
 */
export function groupAlerts<T extends { layer: string; ts: number; station: number }>(
  alerts: T[],
  score: (alert: T) => number,
  signalOf: (alert: T) => string,
): (T & { firstTs: number; lastTs: number; repeatCount: number; peakScore: number })[] {
  const groups = new Map<string, T & {
    firstTs: number; lastTs: number; repeatCount: number; peakScore: number;
  }>();

  for (const alert of alerts) {
    const key = `${alert.layer}|${alert.station}|${signalOf(alert)}`;
    const existing = groups.get(key);
    if (!existing) {
      groups.set(key, {
        ...alert,
        firstTs: alert.ts,
        lastTs: alert.ts,
        repeatCount: 1,
        peakScore: score(alert),
      });
      continue;
    }
    existing.repeatCount += 1;
    existing.firstTs = Math.min(existing.firstTs, alert.ts);
    existing.lastTs = Math.max(existing.lastTs, alert.ts);
    if (score(alert) > existing.peakScore) {
      Object.assign(existing, alert, {
        firstTs: existing.firstTs,
        lastTs: existing.lastTs,
        repeatCount: existing.repeatCount,
        peakScore: score(alert),
      });
    }
  }

  return [...groups.values()].sort(
    (a, b) => b.peakScore - a.peakScore || a.firstTs - b.firstTs,
  );
}
