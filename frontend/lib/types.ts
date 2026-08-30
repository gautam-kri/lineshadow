/**
 * Shapes returned by the FastAPI wrapper in `api/main.py`.
 *
 * These mirror what the Python engine already produces. Keep them descriptive
 * rather than clever: if a field is optional here it is because the engine can
 * genuinely omit it, not because the type was inconvenient.
 */

export type Basis = "direct" | "inferred";
export type ConfidenceLabel = "high" | "medium" | "low";
export type Layer = "L1" | "L2" | "L3";
export type FaultFamily = "none" | "drift" | "slowdown" | "quality";

export interface StationSpec {
  id: number;
  name: string;
  zone: string;
  nominal_cycle_s: number;
  buffer_capacity: number;
  instrumented: boolean;
}

export interface LineModel {
  n_stations: number;
  takt_time_s: number;
  inspection_station: number;
  zones: Record<string, [number, number]>;
  instrumented_ids: number[];
  uninstrumented_ids: number[];
  stations: StationSpec[];
}

export interface ScenarioSummary {
  scenario_id: string;
  split: "tuning" | "holdout";
  seed: number;
  horizon_s: number;
  family: FaultFamily;
  target_station: number | null;
  description: string;
}

/** One station's current belief, as the twin reports it. */
export interface StationState {
  station: number;
  instrumented: boolean;
  cycle_estimate_s: number | null;
  cycle_band_s: number;
  estimate_basis: Basis;
  confidence: number;
  buffer_level: number | null;
  buffer_level_low: number;
  buffer_level_high: number;
  buffer_capacity: number;
  buffer_basis: "exact" | "inferred" | "unknown";
  blocked_ewma_s: number;
  units_seen: number;
  checklist_fail_rate: number | null;
}

export interface Evidence {
  [key: string]: string | number | boolean | null | Evidence;
}

export interface L1Alert {
  layer: "L1";
  ts: number;
  station: number;
  signal: string;
  severity_score: number;
  confidence: number;
  confidence_label: ConfidenceLabel;
  basis: Basis;
  evidence: Evidence;
}

export interface L2Alert {
  layer: "L2";
  ts: number;
  predicted_ts: number;
  station: number;
  kind: "starve" | "block";
  cause_station: number;
  confidence: number;
  confidence_label: ConfidenceLabel;
  basis: Basis;
  evidence: Evidence;
}

export interface L3Alert {
  layer: "L3";
  ts: number;
  vin: string;
  suspect_station: number;
  risk_score: number;
  basis: "unsupervised" | "calibrated";
  confidence: number;
  evidence: Evidence;
}

export type StationAlert = L1Alert | L2Alert;
export type AnyAlert = L1Alert | L2Alert | L3Alert;

export interface AlertBundle {
  l1: L1Alert[];
  l2: L2Alert[];
  l3: L3Alert[];
}

export interface GroundTruth {
  scenario_id: string;
  split: string;
  seed: number;
  horizon_s: number;
  fault: { family: FaultFamily; station?: number; onset_s?: number };
  target_station: number | null;
  target_station_instrumented: boolean | null;
  onset_s: number | null;
  queue_forming: boolean;
  queue_formation_ts: number | null;
  queue_formation_buffer: number | null;
  throughput_loss_units: number;
  notes: string[];
}

export interface ScenarioScore {
  scenario_id: string;
  family: FaultFamily;
  target_station: number | null;
  target_instrumented: boolean | null;
  queue_forming: boolean;
  detected: boolean;
  lead_time_queue_min: number | null;
  detection_vs_onset_min: number | null;
  first_alert_layer: string | null;
  first_alert_signal: string | null;
  containment_rate: number | null;
  n_affected: number | null;
  n_contained: number | null;
  units_early_min: number | null;
  n_alerts: number;
  throughput_loss_units: number;
}

export interface TimelineFrame {
  ts: number;
  stations: {
    station: number;
    cycle_estimate_s: number | null;
    buffer_pressure: number;
    confidence: number;
    basis: Basis;
  }[];
}

export interface RunPayload {
  scenario_id: string;
  split: string;
  sensitivity: number;
  thresholds: { l1: number; l2: number; l3: number };
  stations: StationState[];
  timeline: TimelineFrame[];
  l3_summary: {
    model_source: string;
    calibrated: boolean;
    labels_seen: number;
    suspect_stations: number[];
    station_lift: { station: number; lift: number; n_failed: number }[];
  };
  alerts: AlertBundle;
  ranked_alerts: (StationAlert & { rank_score: number })[];
  ground_truth: GroundTruth;
  score: ScenarioScore;
  /** Only present on /api/perturb responses. */
  horizon_s?: number;
  station_instrumented?: boolean;
}

export interface SweepRow {
  sensitivity: number;
  l1_severity_threshold: number;
  precision: number | null;
  recall: number | null;
  median_lead_time_min: number | null;
  mean_containment_rate: number | null;
  false_alarms_per_shift: number;
  false_alarms_per_shift_low: number;
  false_alarms_per_shift_high: number;
}

export interface HoldoutBundle {
  freeze: { frozen_at_utc: string; source_sha256: string; note: string };
  sensitivity: number;
  seed_range: [number, number];
  scenarios: ScenarioScore[];
  summary: {
    n_detected: number;
    n_faulted: number;
    precision: number | null;
    queue_forming: { n: number; median_lead_time_min: number | null };
    quality: {
      n: number;
      mean_containment_rate: number | null;
      total_contained: number;
      total_affected: number;
    };
    false_alarms_per_shift: { mean: number | null; low: number | null; high: number | null; n: number };
  };
  sweep: SweepRow[];
  line: { n_stations: number; n_instrumented: number; uninstrumented: number[]; takt_time_s: number };
}

export interface PerturbationRequest {
  family: "drift" | "slowdown" | "quality";
  station: number;
  severity_pct: number;
  onset_s: number;
}
