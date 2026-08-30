"""L3: predicting which units will fail final inspection, before they get there.

The cold start is the subtle failure mode here. Inspection labels only exist once
units have reached station 40, so a purely supervised L3 cannot flag anything
until escapes have already happened -- containment would be zero by construction.
So L3 has two halves:

Primary, unsupervised, available from the first unit
    Two pieces of evidence multiply. *Station evidence* is how far a station's
    quality signal has shifted from its own healthy baseline, read straight off
    the EWMA statistic L1 already maintains. *Unit evidence* is how far this
    particular unit's reading sat from that baseline. A unit built through a
    station whose process has visibly shifted is at risk even if its own reading
    looks ordinary, and more at risk if it does not -- which is exactly how a
    process engineer reasons. No labels are involved.

Secondary, supervised, calibrating
    As inspection outcomes arrive they are paired with the features that were
    already known at build time. A classifier (loaded from ``models/l3.joblib`` if
    present, otherwise fitted online once enough labels exist) learns the mapping
    from upstream deviation to failure probability, and the per-station lift
    statistic identifies which stations' signals genuinely predict escapes.

The calibrated half *sharpens* the primary score and never gates it: the reported
risk is the larger of the two, so switching the model off can only remove
precision, never remove coverage. With no model file and no labels yet, the
pipeline still runs and still flags -- which ``tests/test_l3_fallback.py`` and
``tests/test_cold_start.py`` both check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simulator.config import LineConfig

from .config import TwinConfig

FEATURE_NAMES = (
    "max_abs_z",
    "mean_abs_z",
    "n_stations_over_2_sigma",
    "suspect_station_shift",
    "unsupervised_risk",
)
EWMA_UNIT_SD = "sqrt(lambda/(2-lambda))"


def _ramp(value: float, low: float, high: float) -> float:
    """Linear ramp from 0 at ``low`` to 1 at ``high``, clipped."""
    if high <= low:
        return 1.0 if value >= high else 0.0
    return min(1.0, max(0.0, (value - low) / (high - low)))


@dataclass
class UnitProfile:
    """What the twin knows about one in-flight unit."""

    vin: str
    first_seen_ts: float
    max_station: int = 0
    z_by_station: dict[int, float] = field(default_factory=dict)
    flagged_at: float | None = None
    best_emitted_risk: float = 0.0

    def features(self, suspect_shift: float, unsupervised_risk: float) -> list[float]:
        zs = [abs(z) for z in self.z_by_station.values()]
        return [
            max(zs) if zs else 0.0,
            sum(zs) / len(zs) if zs else 0.0,
            float(sum(1 for z in zs if z >= 2.0)),
            suspect_shift,
            unsupervised_risk,
        ]


class L3DefectCorrelator:
    """Scores in-flight units for escape risk and calibrates against inspections."""

    def __init__(self, line: LineConfig, cfg: TwinConfig,
                 model_path: str | Path | None = None) -> None:
        self.line = line
        self.cfg = cfg
        l3 = cfg.l3
        self.station_shift_low = float(l3["station_shift_low"])
        self.station_shift_high = float(l3["station_shift_high"])
        self.unit_z_low = float(l3["unit_z_low"])
        self.unit_z_high = float(l3["unit_z_high"])
        self.floor = cfg.l3_emission_floor
        self.min_labels = int(l3["min_labels_for_calibration"])
        self.min_positives = int(l3["min_positives_for_calibration"])
        self.refit_every = int(l3["refit_every_labels"])
        self.escalation_step = float(l3["escalation_step"])

        self.profiles: dict[str, UnitProfile] = {}
        self.station_shift: dict[int, float] = {sid: 0.0 for sid in line.station_ids}
        self._suspect: set[int] = set()
        self.candidates: list[dict[str, Any]] = []

        self.labels: list[int] = []
        self.features: list[list[float]] = []
        self.station_z_by_outcome: dict[int, tuple[list[float], list[float]]] = {
            sid: ([], []) for sid in line.station_ids
        }
        self.model = self._load_model(model_path or l3.get("model_path"))
        self.model_source = "file" if self.model is not None else "none"
        self._online_model = None
        self._labels_at_last_fit = 0
        self.n_inspected = 0
        self.n_failed = 0

    # ------------------------------------------------------------- model I/O

    @staticmethod
    def _load_model(path: str | Path | None):
        """Load the optional pre-trained classifier; absence is a supported state."""
        if not path:
            return None
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / p
        if not p.exists():
            return None
        try:
            import joblib
            return joblib.load(p)
        except Exception:
            # A missing or unloadable model must never take the pipeline down;
            # the unsupervised path is a complete detector on its own.
            return None

    @property
    def calibrated(self) -> bool:
        return self.model is not None or self._online_model is not None

    def _active_model(self):
        return self.model if self.model is not None else self._online_model

    # ---------------------------------------------------------------- inputs

    def note_passage(self, vin: str, station: int, ts: float) -> UnitProfile:
        """Record that a unit has reached ``station``."""
        prof = self.profiles.get(vin)
        if prof is None:
            prof = UnitProfile(vin=vin, first_seen_ts=ts)
            self.profiles[vin] = prof
        prof.max_station = max(prof.max_station, station)
        return prof

    def on_quality_sample(self, vin: str, station: int, z: float,
                          ewma_stat: float, ts: float) -> None:
        """A per-unit quality reading from an instrumented station."""
        prof = self.note_passage(vin, station, ts)
        prof.z_by_station[station] = z
        self._update_station(station, ewma_stat, ts)
        self._score(prof, ts)

    def on_checklist_sample(self, vin: str, station: int, ewma_stat: float, ts: float) -> None:
        """A sparse manual check at an uninstrumented station."""
        prof = self.note_passage(vin, station, ts)
        self._update_station(station, ewma_stat, ts)
        self._score(prof, ts)

    def on_inspection(self, vin: str, result: str, ts: float) -> None:
        """A final-inspection outcome: the label that calibrates the supervised half."""
        prof = self.profiles.pop(vin, None)
        self.n_inspected += 1
        failed = 1 if result == "fail" else 0
        self.n_failed += failed
        if prof is None:
            return
        suspect_shift, risk, _ = self._assess(prof)
        self.features.append(prof.features(suspect_shift, risk))
        self.labels.append(failed)
        for sid, z in prof.z_by_station.items():
            self.station_z_by_outcome[sid][failed].append(abs(z))
        self._maybe_refit()

    # -------------------------------------------------------------- scoring

    def _update_station(self, station: int, ewma_stat: float, ts: float) -> None:
        self.station_shift[station] = ewma_stat
        evidence = _ramp(abs(ewma_stat), self.station_shift_low, self.station_shift_high)
        was = station in self._suspect
        now = evidence >= self.floor
        if now and not was:
            self._suspect.add(station)
            self._sweep_in_flight(station, ts)
        elif was and not now:
            self._suspect.discard(station)

    def _sweep_in_flight(self, station: int, ts: float) -> None:
        """A station just became suspect: flag every unit already built through it.

        Those units are past the station and have not yet reached inspection, so
        this is the containment opportunity -- catch them in the line rather than
        read about them on the final-inspection report an hour later.
        """
        for prof in list(self.profiles.values()):
            if prof.max_station >= station:
                self._score(prof, ts, triggered_by=station)

    def _assess(self, prof: UnitProfile) -> tuple[float, float, int | None]:
        """Return ``(suspect_station_shift, unsupervised_risk, suspect_station)``."""
        best_risk = 0.0
        best_shift = 0.0
        best_station: int | None = None
        for sid in range(1, prof.max_station + 1):
            shift = self.station_shift.get(sid, 0.0)
            station_evidence = _ramp(abs(shift), self.station_shift_low, self.station_shift_high)
            if station_evidence <= 0.0:
                continue
            z = prof.z_by_station.get(sid)
            if z is None:
                unit_evidence = 0.5  # no per-unit reading here; stay neutral
            else:
                unit_evidence = _ramp(abs(z), self.unit_z_low, self.unit_z_high)
            risk = station_evidence * (0.5 + 0.5 * unit_evidence)
            if risk > best_risk:
                best_risk, best_shift, best_station = risk, abs(shift), sid
        return best_shift, best_risk, best_station

    def _calibrated_probability(self, features: list[float]) -> float | None:
        model = self._active_model()
        if model is None:
            return None
        try:
            return float(model.predict_proba([features])[0][1])
        except Exception:
            return None

    def _score(self, prof: UnitProfile, ts: float, triggered_by: int | None = None) -> None:
        shift, unsup_risk, suspect = self._assess(prof)
        if suspect is None:
            return
        features = prof.features(shift, unsup_risk)
        calibrated = self._calibrated_probability(features)
        risk = unsup_risk if calibrated is None else max(unsup_risk, calibrated)
        basis = "calibrated" if (calibrated is not None and calibrated >= unsup_risk) else "unsupervised"
        # One flag per unit, plus a fresh one only if the case against it has
        # materially strengthened. Re-emitting an unchanged score on every
        # subsequent station would bury the operator without adding information,
        # and containment is scored on the earliest flag either way.
        if risk < self.floor or risk < prof.best_emitted_risk + self.escalation_step:
            return
        prof.best_emitted_risk = risk

        self.candidates.append({
            "layer": "L3",
            "ts": round(ts, 3),
            "vin": prof.vin,
            "suspect_station": suspect,
            "risk_score": round(risk, 4),
            "basis": basis,
            "confidence": round(
                0.9 if self.line.station(suspect).instrumented else 0.5, 3),
            "evidence": {
                "suspect_station_shift_sigma": round(shift, 3),
                "unit_z_at_suspect_station": (
                    None if suspect not in prof.z_by_station
                    else round(prof.z_by_station[suspect], 3)
                ),
                "unsupervised_risk": round(unsup_risk, 4),
                "calibrated_probability": None if calibrated is None else round(calibrated, 4),
                "calibration_labels_seen": len(self.labels),
                "calibration_failures_seen": int(sum(self.labels)),
                "model_source": self.model_source if self.model is not None else (
                    "online" if self._online_model is not None else "none"),
                "stations_observed": len(prof.z_by_station),
                "max_station_reached": prof.max_station,
                "triggered_by_station_becoming_suspect": triggered_by,
                "station_shift_low": self.station_shift_low,
                "station_shift_high": self.station_shift_high,
            },
        })
        if prof.flagged_at is None:
            prof.flagged_at = ts

    # ----------------------------------------------------------- calibration

    def _maybe_refit(self) -> None:
        """Fit the online logistic model once labels are plentiful enough."""
        if self.model is not None:
            return  # a pre-trained model takes precedence
        n = len(self.labels)
        positives = sum(self.labels)
        if n < self.min_labels or positives < self.min_positives:
            return
        if n - self._labels_at_last_fit < self.refit_every:
            return
        try:
            from sklearn.linear_model import LogisticRegression
            model = LogisticRegression(max_iter=500, class_weight="balanced")
            model.fit(self.features, self.labels)
            self._online_model = model
            self._labels_at_last_fit = n
        except Exception:
            self._online_model = None

    def station_lift(self) -> list[dict[str, Any]]:
        """Which stations' quality signals actually separate failures from passes."""
        rows: list[dict[str, Any]] = []
        for sid, (passed, failed) in self.station_z_by_outcome.items():
            if len(failed) < 3 or len(passed) < 3:
                continue
            mp = sum(passed) / len(passed)
            mf = sum(failed) / len(failed)
            rows.append({
                "station": sid,
                "mean_abs_z_passed": round(mp, 3),
                "mean_abs_z_failed": round(mf, 3),
                "lift": round(mf - mp, 3),
                "n_failed": len(failed),
                "n_passed": len(passed),
            })
        rows.sort(key=lambda r: -r["lift"])
        return rows

    def summary(self) -> dict[str, Any]:
        return {
            "model_source": self.model_source if self.model is not None else (
                "online" if self._online_model is not None else "none"),
            "calibrated": self.calibrated,
            "labels_seen": len(self.labels),
            "failures_seen": int(sum(self.labels)),
            "units_inspected": self.n_inspected,
            "units_failed": self.n_failed,
            "units_in_flight": len(self.profiles),
            "suspect_stations": sorted(self._suspect),
            "station_lift": self.station_lift()[:8],
            "ewma_unit_scale": EWMA_UNIT_SD,
            "feature_names": list(FEATURE_NAMES),
        }


def first_flag_by_vin(candidates: list[dict[str, Any]]) -> dict[str, float]:
    """Earliest flag timestamp per VIN, which is what containment is scored on."""
    out: dict[str, float] = {}
    for c in candidates:
        vin = c["vin"]
        if vin not in out or c["ts"] < out[vin]:
            out[vin] = c["ts"]
    return out
