#!/usr/bin/env python3
"""Train Auto entry classifier from offline dataset JSON.

Writes versioned joblib + manifest under models/auto_entry/.
Does NOT enable the live gate or mutate trading_config.

Requires: pip install -r scripts/requirements-auto-ml.txt

Usage:
  python3 scripts/build_auto_ml_dataset.py --demo
  python3 scripts/train_auto_entry_model.py --dataset docs/analysis/auto-ml-dataset.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from auto_ml_features import FEATURE_NAMES, FEATURE_VERSION  # noqa: E402

MIN_ROWS = 6  # demo-friendly floor; prod retrain should raise this


def _require_sklearn():
    try:
        import joblib  # noqa: F401
        from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: F401
        from sklearn.metrics import (  # noqa: F401
            accuracy_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import train_test_split  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "Missing ML deps. Install with:\n"
            "  pip install -r scripts/requirements-auto-ml.txt\n"
            f"Detail: {e}"
        ) from e


def load_dataset(path: Path) -> tuple[list[list[float]], list[int], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta") if isinstance(data, dict) else {}
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise SystemExit("Dataset must be {meta, rows} or a list of rows")
    X: list[list[float]] = []
    y: list[int] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if "x" not in r or "y" not in r:
            continue
        x = r["x"]
        if not isinstance(x, list) or len(x) != len(FEATURE_NAMES):
            continue
        X.append([float(v) for v in x])
        y.append(int(r["y"]))
    return X, y, meta if isinstance(meta, dict) else {}


def next_version(out_dir: Path) -> int:
    versions: list[int] = []
    for name in ("manifest.json", "candidate_manifest.json"):
        path = out_dir / name
        if not path.exists():
            continue
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
            versions.append(int(m.get("version") or 0))
        except Exception:
            continue
    for p in out_dir.glob("auto_entry_v*.joblib"):
        try:
            # auto_entry_v12.joblib
            stem = p.stem  # auto_entry_v12
            versions.append(int(stem.rsplit("v", 1)[-1]))
        except Exception:
            continue
    return (max(versions) + 1) if versions else 1


def train(
    X: list[list[float]],
    y: list[int],
    *,
    test_size: float,
    seed: int,
) -> tuple[Any, dict[str, Any]]:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import train_test_split

    classes = set(y)
    if len(classes) < 2:
        # Degenerate: still fit so demos work; metrics note single-class
        clf = HistGradientBoostingClassifier(max_depth=3, max_iter=50, random_state=seed)
        clf.fit(X, y)
        preds = clf.predict(X)
        metrics = {
            "holdout": False,
            "n_train": len(y),
            "n_test": 0,
            "accuracy": float(accuracy_score(y, preds)),
            "precision": float(precision_score(y, preds, zero_division=0)),
            "recall": float(recall_score(y, preds, zero_division=0)),
            "roc_auc": None,
            "note": "single_class_fit_on_all",
        }
        return clf, metrics

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    clf = HistGradientBoostingClassifier(
        max_depth=3,
        max_iter=80,
        learning_rate=0.08,
        random_state=seed,
    )
    clf.fit(X_train, y_train)
    preds = clf.predict(X_test)
    proba = clf.predict_proba(X_test)[:, 1] if hasattr(clf, "predict_proba") else None
    metrics = {
        "holdout": True,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "accuracy": float(accuracy_score(y_test, preds)),
        "precision": float(precision_score(y_test, preds, zero_division=0)),
        "recall": float(recall_score(y_test, preds, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, proba)) if proba is not None else None,
    }
    return clf, metrics


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train Auto entry ML model (offline)")
    p.add_argument(
        "--dataset",
        type=Path,
        default=_REPO_ROOT / "docs" / "analysis" / "auto-ml-dataset.json",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "models" / "auto_entry",
    )
    p.add_argument("--test-size", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--min-rows", type=int, default=MIN_ROWS)
    p.add_argument(
        "--no-promote",
        action="store_true",
        help="Write versioned + candidate artifacts only (do not update current.joblib)",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    _require_sklearn()
    import joblib

    args = parse_args(argv)
    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}", file=sys.stderr)
        print("Run: python3 scripts/build_auto_ml_dataset.py --demo", file=sys.stderr)
        return 2

    X, y, ds_meta = load_dataset(args.dataset)
    if len(X) < args.min_rows:
        print(
            f"Need at least {args.min_rows} labeled rows, got {len(X)}.",
            file=sys.stderr,
        )
        return 2

    clf, metrics = train(X, y, test_size=args.test_size, seed=args.seed)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    version = next_version(args.out_dir)
    model_name = f"auto_entry_v{version}.joblib"
    model_path = args.out_dir / model_name
    payload = {
        "model": clf,
        "feature_names": list(FEATURE_NAMES),
        "feature_version": FEATURE_VERSION,
        "version": version,
    }
    joblib.dump(payload, model_path)

    manifest = {
        "version": version,
        "model_file": model_name,
        "feature_names": list(FEATURE_NAMES),
        "feature_version": FEATURE_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_meta": {
            "source": ds_meta.get("source"),
            "n_dataset_rows": ds_meta.get("n_dataset_rows"),
            "n_positive": ds_meta.get("n_positive"),
            "n_negative": ds_meta.get("n_negative"),
            "label_def": ds_meta.get("label_def"),
        },
        "n_fit_rows": len(X),
        "metrics": metrics,
        "autonomous_promote": False,
        "live_gate_enabled": False,
        "note": "candidate artifact — promote via retrain_and_promote_auto_entry.py (PR-ML-C)",
    }
    (args.out_dir / "candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    joblib.dump(payload, args.out_dir / "candidate.joblib")

    promoted_current = False
    if not args.no_promote:
        # Backward-compatible default: also refresh current + manifest
        joblib.dump(payload, args.out_dir / "current.joblib")
        (args.out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        promoted_current = True

    print(
        json.dumps(
            {
                "wrote": str(model_path),
                "candidate": str(args.out_dir / "candidate.joblib"),
                "updated_current": promoted_current,
                "manifest": manifest,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
