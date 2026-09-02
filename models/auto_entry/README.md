# Auto entry ML artifacts (offline train output)

Versioned `*.joblib` + `manifest.json` are produced by:

```bash
pip install -r scripts/requirements-auto-ml.txt
python3 scripts/build_auto_ml_dataset.py --demo
python3 scripts/train_auto_entry_model.py
```

Live inference gate is **not** enabled here (PR-ML-B).

Phase 2 SL/TP manifests (`sltp_manifest.json`, `sltp_candidate_manifest.json`,
`pending_sltp_promote.json`, merit reports) live in the same directory:

```bash
python3 scripts/retrain_and_promote_auto_sltp.py --demo --min-rows 20
```

Promote via `POST /api/config/auto-ml/sltp/promote` or Strategy Config → Auto panel.
Live gate: `AUTO_ML_SLTP_ENABLED=true` (default **false**).
