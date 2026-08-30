# data/

Place a vehicle supply-chain dataset here as `supply_chain.csv`, then run:

```bash
python scripts/calibrate.py
```

The schema is not assumed. `scripts/calibrate.py` prints every column it finds,
fuzzy-matches on name tokens for delivery / lead-time / delay / quantity / date /
defect fields, and prints exactly what it matched and every assumption it made
(including the time unit it inferred) so the mapping can be checked by hand. It
then writes the fitted inbound-delay distribution and base defect rate into
`config/line.yaml`.

**The pipeline runs with or without this file.** With no dataset present,
`calibrate.py` falls back to documented defaults and says so loudly: a 0.5% base
defect rate (the order of magnitude of the public Bosch production-line dataset)
and drift shapes following AI4I 2020 qualitatively.

CSV files in this directory are gitignored.
