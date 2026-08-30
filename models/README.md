# models/

`l3.joblib` — the **optional** calibrated half of L3, produced by:

```bash
python scripts/train_l3.py
```

Trained on the tuning split only; the script checks every scenario by split, by
id prefix and by seed range and fails hard if a holdout scenario appears.

The twin loads this file automatically if it exists and falls back cleanly to
L3's unsupervised path if it does not. That fallback is a supported, tested state
— see `tests/test_l3_fallback.py`. Delete the file and the pipeline still runs and
still flags at-risk units.

Model files are gitignored; regenerate with the command above.
