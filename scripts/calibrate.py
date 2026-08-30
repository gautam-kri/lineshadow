"""Calibrate the simulator against a real vehicle supply-chain dataset.

    python scripts/calibrate.py                       # uses data/supply_chain.csv
    python scripts/calibrate.py --csv other.csv       # any CSV
    python scripts/calibrate.py --dry-run             # report only, write nothing

The dataset's schema is unknown in advance, so this script is written defensively:
it prints every column it found, states exactly which ones it matched and to what,
states every assumption it made (including units), and then writes the fitted
parameters into ``config/line.yaml``. A human can check the mapping from the
output alone.

If the file is missing or unusable, documented defaults are used instead and the
script says so loudly. **The pipeline runs with or without the dataset.**

Defaults, and why:
  * base defect rate 0.5% — the order of magnitude of the public Bosch production
    line dataset, whose positive (failed) class sits near 0.6%.
  * drift shapes are qualitatively per AI4I 2020: gradual tool-wear ramps over
    hundreds of cycles rather than step changes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CSV = REPO_ROOT / "data" / "supply_chain.csv"
LINE_CONFIG = REPO_ROOT / "config" / "line.yaml"

DEFAULTS = {
    "part_delay_probability": 0.03,
    "part_delay_median_s": 150.0,
    "part_delay_sigma_log": 0.7,
    "base_defect_rate": 0.005,
}

DELAY_WORDS = ("delay", "late", "lateness", "slip", "deviation", "variance", "overdue")
LEADTIME_WORDS = ("leadtime", "lead", "transit", "shipping", "shipment", "transport", "duration")
PROMISED_WORDS = ("promised", "expected", "scheduled", "planned", "due", "committed", "order")
ACTUAL_WORDS = ("actual", "delivered", "delivery", "receipt", "received", "arrival", "arrived")
QUANTITY_WORDS = ("quantity", "qty", "units", "volume", "amount", "shipped", "produced")
DEFECT_WORDS = ("defect", "defective", "reject", "scrap", "fail", "failure", "nonconform",
                "quality", "ppm", "flaw", "damage")
UNIT_HINTS = {"sec": 1.0, "second": 1.0, "min": 60.0, "minute": 60.0,
              "hour": 3600.0, "hr": 3600.0, "day": 86400.0, "week": 604800.0}
# A multi-day supplier delay cannot be replayed literally inside a 15 h shift-pair.
# The *shape* is taken from the data; the magnitude is capped at this many takts.
DELAY_CAP_TAKTS = 8.0


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def tokenise(name: str) -> list[str]:
    """Split a column name into lowercase word tokens.

    Matching on tokens rather than raw substrings avoids the classic false hit:
    the keyword "late" is a substring of "unrelated", so substring matching would
    happily calibrate inbound delivery delay from a column called `unrelated`.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
    return [tok for tok in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if tok]


@dataclass
class Finding:
    """One column match, recorded so a human can audit the mapping."""

    role: str
    column: str | None
    reason: str


@dataclass
class Calibration:
    """The fitted parameters plus the full audit trail behind them."""

    source: str
    part_delay_probability: float
    part_delay_median_s: float
    part_delay_sigma_log: float
    base_defect_rate: float
    findings: list[Finding] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    used_defaults: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.assumptions.append(text)


def _token_hits(tokens: list[str], words: tuple[str, ...]) -> list[str]:
    """Keywords that match a column's tokens, exactly or as a clear prefix."""
    hits = []
    for word in words:
        for tok in tokens:
            exact = tok == word
            prefix = len(word) >= 5 and tok.startswith(word)
            abbrev = len(tok) >= 5 and word.startswith(tok) and len(tok) >= len(word) - 2
            if exact or prefix or abbrev:
                hits.append(word)
                break
    return hits


def _match(columns: list[str], words: tuple[str, ...],
           exclude_words: tuple[str, ...] = (),
           exclude_columns: tuple[str, ...] = ()) -> str | None:
    """Best fuzzy column match, longest matching keyword wins."""
    scored: list[tuple[int, int, str]] = []
    for col in columns:
        if col in exclude_columns:
            continue
        tokens = tokenise(col)
        if exclude_words and _token_hits(tokens, exclude_words):
            continue
        hits = _token_hits(tokens, words)
        if hits:
            scored.append((-max(len(w) for w in hits), len(normalise(col)), col))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def _numeric_positive(df: pd.DataFrame, column: str | None) -> str | None:
    """Keep a candidate quantity column only if it is genuinely numeric and positive."""
    if column is None:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty or float(values.sum()) <= 0:
        return None
    return column


def _unit_scale(column: str, values: pd.Series) -> tuple[float, str]:
    """Seconds-per-unit for a duration column, from its name or its magnitude."""
    n = normalise(column)
    for hint, scale in UNIT_HINTS.items():
        if hint in n:
            return scale, f"column name contains '{hint}'"
    median = float(np.nanmedian(np.abs(values.to_numpy(dtype=float))))
    if median <= 60:
        return 86400.0, f"no unit in the name; median |value| {median:.1f} looks like DAYS"
    if median <= 1000:
        return 3600.0, f"no unit in the name; median |value| {median:.1f} looks like HOURS"
    return 1.0, f"no unit in the name; median |value| {median:.1f} assumed to be SECONDS"


def _fit_delay(delays_s: np.ndarray, takt_s: float, cal: Calibration) -> None:
    """Fit a lognormal to the positive (late) deliveries."""
    finite = delays_s[np.isfinite(delays_s)]
    late = finite[finite > 0]
    if finite.size < 10 or late.size < 5:
        cal.used_defaults.append("part_delay (too few usable late deliveries)")
        return

    probability = float(late.size / finite.size)
    raw_median = float(np.median(late))
    sigma = float(np.std(np.log(late[late > 0]), ddof=1)) if late.size > 2 else 0.7

    cap = DELAY_CAP_TAKTS * takt_s
    capped = min(raw_median, cap)
    cal.part_delay_probability = float(np.clip(probability, 0.005, 0.15))
    cal.part_delay_median_s = float(round(capped, 1))
    cal.part_delay_sigma_log = float(np.clip(sigma, 0.3, 1.5))

    cal.note(f"late-delivery share {probability:.3f} -> part_delay.probability "
             f"{cal.part_delay_probability:.3f} (clipped to [0.005, 0.15])")
    cal.note(f"log-scale spread of late deliveries {sigma:.3f} -> sigma_log "
             f"{cal.part_delay_sigma_log:.3f} (clipped to [0.3, 1.5])")
    if raw_median > cap:
        cal.note(
            f"median late delivery is {raw_median / 3600:.1f} h, which cannot be replayed "
            f"literally inside a 15 h run: it would starve the line for the whole horizon. "
            f"The distribution SHAPE is taken from the data; the MAGNITUDE is capped at "
            f"{DELAY_CAP_TAKTS:.0f} takts = {cap:.0f}s. A supplier delay then manifests as "
            f"an upstream starve, which is exactly how the twin should see it."
        )
    else:
        cal.note(f"median late delivery {raw_median:.0f}s used directly (under the "
                 f"{cap:.0f}s cap)")


def _fit_defect_rate(df: pd.DataFrame, defect_col: str, qty_col: str | None,
                     cal: Calibration) -> None:
    """Fit a base defect rate from whatever form the defect column takes."""
    series = pd.to_numeric(df[defect_col], errors="coerce").dropna()
    if series.empty:
        cal.used_defaults.append(f"base_defect_rate (column '{defect_col}' is not numeric)")
        return

    n = normalise(defect_col)
    values = series.to_numpy(dtype=float)
    if "ppm" in n:
        rate = float(np.mean(values) / 1e6)
        how = "column is in PPM; divided by 1e6"
    elif set(np.unique(values)) <= {0.0, 1.0}:
        rate = float(np.mean(values))
        how = "column is binary; took the mean"
    elif values.max() <= 1.0:
        rate = float(np.mean(values))
        how = "values all in [0,1]; treated as a rate and took the mean"
    elif qty_col is not None:
        qty = pd.to_numeric(df[qty_col], errors="coerce")
        paired = pd.DataFrame({"d": series, "q": qty}).dropna()
        total = float(paired["q"].sum())
        if total <= 0:
            cal.used_defaults.append("base_defect_rate (quantity column sums to zero)")
            return
        rate = float(paired["d"].sum() / total)
        how = f"counts divided by total quantity from '{qty_col}'"
    else:
        rate = float(np.mean(values) / 100.0)
        how = "values look like percentages; divided by 100"

    clipped = float(np.clip(rate, 0.0005, 0.05))
    cal.base_defect_rate = round(clipped, 6)
    cal.note(f"base defect rate {rate:.5f} -> {clipped:.5f} ({how}; clipped to [0.0005, 0.05])")


def calibrate_from_csv(path: Path, takt_s: float, verbose: bool = True) -> Calibration:
    """Inspect a CSV, fit what can be fitted, and fall back loudly for the rest."""
    cal = Calibration(source=str(path), **DEFAULTS)  # type: ignore[arg-type]

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        cal.source = "defaults"
        cal.used_defaults = ["part_delay", "base_defect_rate"]
        cal.note(f"could not read {path}: {exc}")
        return cal

    columns = list(df.columns)
    if verbose:
        print(f"\nRead {path}  ->  {len(df)} rows x {len(columns)} columns")
        print("Columns found:")
        for col in columns:
            sample = df[col].dropna().head(3).tolist()
            print(f"    {col!r:38s} dtype={str(df[col].dtype):10s} e.g. {sample}")

    delay_col = _match(columns, DELAY_WORDS)
    lead_col = _match(columns, LEADTIME_WORDS, exclude_words=("delay",))
    promised_col = _match(columns, PROMISED_WORDS)
    # A column named `promised_delivery_date` contains both a promised word and
    # an actual word; without excluding the column already taken for the promised
    # role, both roles collapse onto it and the date pair is silently lost.
    actual_col = _match(columns, ACTUAL_WORDS, exclude_words=PROMISED_WORDS,
                        exclude_columns=(promised_col,) if promised_col else ())
    qty_col = _numeric_positive(df, _match(columns, QUANTITY_WORDS))
    defect_col = _match(columns, DEFECT_WORDS)

    delays_s: np.ndarray | None = None
    if delay_col is not None:
        values = pd.to_numeric(df[delay_col], errors="coerce").dropna()
        if not values.empty:
            scale, why = _unit_scale(delay_col, values)
            delays_s = values.to_numpy(dtype=float) * scale
            cal.findings.append(Finding("inbound delay", delay_col,
                                        f"explicit delay column; unit scale {scale:g}s ({why})"))

    if delays_s is None and promised_col and actual_col and promised_col != actual_col:
        promised = pd.to_datetime(df[promised_col], errors="coerce")
        actual = pd.to_datetime(df[actual_col], errors="coerce")
        diff = (actual - promised).dt.total_seconds().dropna()
        if not diff.empty:
            delays_s = diff.to_numpy(dtype=float)
            cal.findings.append(Finding(
                "inbound delay", f"{actual_col} - {promised_col}",
                "no explicit delay column; differenced a promised/actual date pair"))

    if delays_s is None and lead_col is not None:
        values = pd.to_numeric(df[lead_col], errors="coerce").dropna()
        if not values.empty:
            scale, why = _unit_scale(lead_col, values)
            centred = (values - values.median()).to_numpy(dtype=float) * scale
            delays_s = centred
            cal.findings.append(Finding(
                "inbound delay", lead_col,
                f"no delay column and no date pair; used deviation of lead time from its "
                f"own median; unit scale {scale:g}s ({why})"))

    if delays_s is None:
        cal.findings.append(Finding("inbound delay", None,
                                    "no delay, date-pair or lead-time column matched"))
        cal.used_defaults.append("part_delay")
    else:
        _fit_delay(delays_s, takt_s, cal)

    if defect_col is not None:
        cal.findings.append(Finding("defect rate", defect_col, "fuzzy match on quality wording"))
        if qty_col is not None:
            cal.findings.append(Finding("quantity", qty_col, "used as the defect denominator"))
        _fit_defect_rate(df, defect_col, qty_col, cal)
    else:
        cal.findings.append(Finding("defect rate", None, "no defect/quality column matched"))
        cal.used_defaults.append("base_defect_rate")

    return cal


def default_calibration() -> Calibration:
    cal = Calibration(source="defaults", **DEFAULTS)  # type: ignore[arg-type]
    cal.used_defaults = ["part_delay", "base_defect_rate"]
    cal.findings.append(Finding("inbound delay", None, "no dataset available"))
    cal.findings.append(Finding("defect rate", None, "no dataset available"))
    return cal


def write_line_config(cal: Calibration, path: Path = LINE_CONFIG) -> None:
    """Update the part-arrival and quality blocks, preserving the file's header."""
    text = path.read_text(encoding="utf-8")
    header_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    header = "\n".join(header_lines).rstrip() + "\n\n" if header_lines else ""

    cfg = yaml.safe_load(text)
    arrival = cfg["line"]["arrival"]["part_delay"]
    arrival["source"] = cal.source
    arrival["probability"] = round(cal.part_delay_probability, 5)
    arrival["median_s"] = round(cal.part_delay_median_s, 2)
    arrival["sigma_log"] = round(cal.part_delay_sigma_log, 4)

    quality = cfg["line"]["quality"]
    quality["source"] = cal.source
    quality["base_defect_rate"] = round(cal.base_defect_rate, 6)

    cfg["line"]["calibration"] = {
        "source": cal.source,
        "fields_used": [{"role": f.role, "column": f.column, "reason": f.reason}
                        for f in cal.findings],
        "assumptions": list(cal.assumptions),
        "defaults_used_for": list(cal.used_defaults),
    }

    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
        yaml.safe_dump(cfg, fh, sort_keys=False, default_flow_style=False, width=200)


def print_report(cal: Calibration) -> None:
    rule = "=" * 78
    print("\n" + rule)
    print("CALIBRATION REPORT")
    print(rule)
    print(f"  source: {cal.source}")
    print("\n  Column mapping (check this):")
    for f in cal.findings:
        print(f"    {f.role:16s} <- {str(f.column):32s} : {f.reason}")
    if cal.assumptions:
        print("\n  Assumptions made:")
        for note in cal.assumptions:
            for i, chunk in enumerate(_wrap(note, 70)):
                print(("    - " if i == 0 else "      ") + chunk)
    print("\n  Fitted parameters:")
    print(f"    part_delay.probability : {cal.part_delay_probability:.5f}")
    print(f"    part_delay.median_s    : {cal.part_delay_median_s:.1f}")
    print(f"    part_delay.sigma_log   : {cal.part_delay_sigma_log:.4f}")
    print(f"    base_defect_rate       : {cal.base_defect_rate:.5f}")
    if cal.used_defaults:
        print("\n  !! FELL BACK TO DOCUMENTED DEFAULTS FOR: " + ", ".join(cal.used_defaults))
        print("     base defect rate 0.5% is the order of magnitude of the public Bosch")
        print("     production-line dataset; drift shapes follow AI4I 2020 qualitatively.")
        print("     These are documented defaults, NOT fits to the supplied data.")
    print(rule)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/calibrate.py", description=__doc__)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write config")
    ap.add_argument("--line", type=Path, default=LINE_CONFIG)
    args = ap.parse_args(argv)

    takt = float(yaml.safe_load(args.line.read_text(encoding="utf-8"))["line"]["takt_time_s"])

    if not args.csv.exists():
        print(f"\n!! DATASET NOT FOUND: {args.csv}")
        print("!! Falling back to documented defaults. The pipeline runs either way.")
        cal = default_calibration()
    else:
        cal = calibrate_from_csv(args.csv, takt)

    print_report(cal)
    if args.dry_run:
        print("\n--dry-run: config/line.yaml left unchanged.")
        return 0

    write_line_config(cal, args.line)
    print(f"\nwrote {args.line}")
    print("Re-run `python -m simulator --split tuning` to regenerate runs with these parameters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
