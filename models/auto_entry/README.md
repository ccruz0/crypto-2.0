# Auto entry ML artifacts (offline train output)

Versioned `*.joblib` + `manifest.json` are produced by:

```bash
pip install -r scripts/requirements-auto-ml.txt
python3 scripts/build_auto_ml_dataset.py --demo
python3 scripts/train_auto_entry_model.py
```

Live inference gate is **not** enabled here (PR-ML-B).
