"""Tests for locked Auto strategy preset (Phase 1 scaffold)."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.config import _merge_strategy_rules_preserving_locked_auto
from app.services.config_loader import _ensure_auto_strategy_preset, get_strategy_rules
from app.services.strategy_profiles import RiskApproach, StrategyType, resolve_strategy_profile


AUTO_SEED = {
    "notificationProfile": "swing",
    "locked": True,
    "seed_from": "swing-conservative",
    "param_version": 1,
    "rules": {
        "Learned": {
            "rsi": {"buyBelow": 30, "sellAbove": 70},
            "maChecks": {"ema10": True, "ma50": True, "ma200": True},
            "sl": {"atrMult": 1.5, "fallbackPct": 3.0},
            "tp": {"rr": 1.5},
            "volumeMinRatio": 1.0,
            "minPriceChangePct": 3.0,
            "alertCooldownMinutes": 0.1667,
        }
    },
}


def test_ensure_auto_seeds_without_touching_coins():
    cfg = {
        "strategy_rules": {
            "swing": {
                "notificationProfile": "swing",
                "rules": {
                    "Conservative": deepcopy(AUTO_SEED["rules"]["Learned"]),
                },
            }
        },
        "coins": {"BTC_USDT": {"preset": "swing-conservative"}},
    }
    _ensure_auto_strategy_preset(cfg, AUTO_SEED)
    assert "auto" in cfg["strategy_rules"]
    assert cfg["strategy_rules"]["auto"]["locked"] is True
    assert "Learned" in cfg["strategy_rules"]["auto"]["rules"]
    assert cfg["coins"]["BTC_USDT"]["preset"] == "swing-conservative"


def test_merge_rejects_auto_rule_mutation():
    existing = {"strategy_rules": {"auto": deepcopy(AUTO_SEED), "swing": {}}}
    incoming = {
        "auto": {
            **deepcopy(AUTO_SEED),
            "rules": {
                "Learned": {
                    **deepcopy(AUTO_SEED["rules"]["Learned"]),
                    "rsi": {"buyBelow": 99, "sellAbove": 70},
                }
            },
        },
        "swing": {},
    }
    with pytest.raises(HTTPException) as exc:
        _merge_strategy_rules_preserving_locked_auto(existing, incoming)
    assert exc.value.status_code == 403


def test_merge_preserves_auto_when_omitted():
    existing = {"strategy_rules": {"auto": deepcopy(AUTO_SEED), "swing": {"x": 1}}}
    incoming = {"swing": {"x": 2}}
    merged = _merge_strategy_rules_preserving_locked_auto(existing, incoming)
    assert merged["auto"] == AUTO_SEED
    assert merged["swing"] == {"x": 2}


def test_resolve_auto_preset():
    cfg = {"coins": {"ETH_USDT": {"preset": "auto"}}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile("ETH_USDT")
    assert strategy == StrategyType.AUTO
    assert approach == RiskApproach.CONSERVATIVE


def test_get_strategy_rules_auto_uses_learned(tmp_path, monkeypatch):
    import json
    from app.services import config_loader

    cfg = {
        "strategy_rules": {
            "auto": deepcopy(AUTO_SEED),
            "swing": {
                "notificationProfile": "swing",
                "rules": {"Conservative": deepcopy(AUTO_SEED["rules"]["Learned"])},
            },
        },
        "coins": {},
        "defaults": {},
    }
    path = tmp_path / "trading_config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setenv("TRADING_CONFIG_PATH", str(path))
    config_loader.invalidate_config_cache = getattr(
        config_loader, "invalidate_config_cache", lambda: None
    )
    # Clear any path cache by reloading
    rules = get_strategy_rules("auto", "Aggressive")
    assert rules["rsi"]["buyBelow"] == 30
    assert rules["volumeMinRatio"] == 1.0
