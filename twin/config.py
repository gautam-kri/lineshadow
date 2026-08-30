"""Twin configuration, and the single monotone sensitivity -> threshold mapping.

Everything tunable lives in ``config/twin.yaml``. A single master ``sensitivity``
in [0,1] scales every alert threshold; higher sensitivity always means a weakly
larger alert set, because each threshold is linear and decreasing in sensitivity
and the twin emits candidates down to the sensitivity-1 floor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TWIN_CONFIG = REPO_ROOT / "config" / "twin.yaml"


def config_hash(path: str | Path) -> str:
    """SHA-256 of a config file's bytes. Used by the freeze protocol."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class TwinConfig:
    """Parsed ``config/twin.yaml`` plus the sensitivity mapping it defines."""

    sensitivity: float
    warmup: dict[str, Any]
    l1: dict[str, Any]
    sparse: dict[str, Any]
    l2: dict[str, Any]
    l3: dict[str, Any]
    source_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- thresholds

    @staticmethod
    def _interpolate(at_zero: float, at_one: float, sensitivity: float) -> float:
        s = min(1.0, max(0.0, float(sensitivity)))
        return at_zero + s * (at_one - at_zero)

    def l1_threshold(self, sensitivity: float | None = None) -> float:
        """Minimum L1 severity that counts as an alert. Decreasing in sensitivity."""
        s = self.sensitivity if sensitivity is None else sensitivity
        return self._interpolate(self.l1["severity_at_sensitivity_0"],
                                 self.l1["severity_at_sensitivity_1"], s)

    def l2_threshold(self, sensitivity: float | None = None) -> float:
        """Minimum L2 confidence that counts as an alert. Decreasing in sensitivity."""
        s = self.sensitivity if sensitivity is None else sensitivity
        return self._interpolate(self.l2["confidence_at_sensitivity_0"],
                                 self.l2["confidence_at_sensitivity_1"], s)

    def l3_threshold(self, sensitivity: float | None = None) -> float:
        """Minimum L3 risk score that counts as a flag. Decreasing in sensitivity."""
        s = self.sensitivity if sensitivity is None else sensitivity
        return self._interpolate(self.l3["risk_at_sensitivity_0"],
                                 self.l3["risk_at_sensitivity_1"], s)

    @property
    def l1_emission_floor(self) -> float:
        return float(self.l1["severity_at_sensitivity_1"])

    @property
    def l2_emission_floor(self) -> float:
        return float(self.l2["confidence_at_sensitivity_1"])

    @property
    def l3_emission_floor(self) -> float:
        return float(self.l3["risk_at_sensitivity_1"])

    def with_sensitivity(self, sensitivity: float) -> "TwinConfig":
        """A copy at a different master sensitivity."""
        return TwinConfig(
            sensitivity=float(sensitivity), warmup=self.warmup, l1=self.l1,
            sparse=self.sparse, l2=self.l2, l3=self.l3,
            source_path=self.source_path, raw=self.raw,
        )


def load_twin_config(path: str | Path = DEFAULT_TWIN_CONFIG,
                     sensitivity: float | None = None) -> TwinConfig:
    """Load ``config/twin.yaml`` (or a frozen copy of it)."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    cfg = raw["twin"]
    for a, b in (("l1", "severity"), ("l2", "confidence"), ("l3", "risk")):
        lo, hi = cfg[a][f"{b}_at_sensitivity_0"], cfg[a][f"{b}_at_sensitivity_1"]
        if not hi <= lo:
            raise ValueError(
                f"twin.{a}.{b}_at_sensitivity_1 ({hi}) must be <= "
                f"..._at_sensitivity_0 ({lo}); thresholds must fall as sensitivity rises"
            )
    return TwinConfig(
        sensitivity=float(cfg["sensitivity"] if sensitivity is None else sensitivity),
        warmup=dict(cfg["warmup"]),
        l1=dict(cfg["l1"]),
        sparse=dict(cfg["sparse"]),
        l2=dict(cfg["l2"]),
        l3=dict(cfg["l3"]),
        source_path=p,
        raw=raw,
    )
