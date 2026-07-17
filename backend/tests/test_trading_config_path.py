"""TRADING_CONFIG_PATH must persist strategy edits across container recreates."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CONFIG_LOADER_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "config_loader.py"


def _load_config_loader(monkeypatch, volume_cfg: Path):
    """Load config_loader.py as a standalone module (avoids heavy app.services imports)."""
    monkeypatch.setenv("TRADING_CONFIG_PATH", str(volume_cfg))
    module_name = "trading_config_loader_under_test"
    # Drop prior load so env is re-read
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_LOADER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    assert mod.get_config_path() == volume_cfg
    return mod


@pytest.fixture
def config_loader_mod(monkeypatch, tmp_path):
    volume_cfg = tmp_path / "data" / "trading_config.json"
    mod = _load_config_loader(monkeypatch, volume_cfg)
    yield mod, volume_cfg, tmp_path
    monkeypatch.delenv("TRADING_CONFIG_PATH", raising=False)
    sys.modules.pop("trading_config_loader_under_test", None)


def test_get_config_path_honors_env(config_loader_mod):
    cl, volume_cfg, _ = config_loader_mod
    assert cl.get_config_path() == volume_cfg
    assert cl.CONFIG_PATH == volume_cfg


def test_save_and_load_roundtrip_on_volume_path(config_loader_mod):
    cl, volume_cfg, _ = config_loader_mod
    cfg = {
        "version": 1,
        "defaults": {"timeframe": "4h", "preset": "swing"},
        "presets": {},
        "strategy_rules": {},
        "coins": {"BTC_USD": {"preset": "scalp-aggressive", "overrides": {}}},
    }
    saved = cl.save_config(cfg)
    assert volume_cfg.exists()
    assert saved["coins"]["BTC_USD"]["preset"] == "scalp-aggressive"

    loaded = cl.load_config()
    assert loaded["coins"]["BTC_USD"]["preset"] == "scalp-aggressive"
    assert json.loads(volume_cfg.read_text())["coins"]["BTC_USD"]["preset"] == "scalp-aggressive"


def test_seed_from_baked_config_when_volume_missing(config_loader_mod, tmp_path):
    cl, volume_cfg, root = config_loader_mod
    seed = root / "app" / "trading_config.json"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(
        json.dumps(
            {
                "version": 1,
                "defaults": {"preset": "swing"},
                "coins": {"ETH_USD": {"preset": "swing-aggressive", "overrides": {}}},
            }
        )
    )
    cl._SEED_CANDIDATES = [seed, Path("/nonexistent/trading_config.json")]

    assert not volume_cfg.exists()
    loaded = cl.load_config()
    assert volume_cfg.exists()
    assert loaded["coins"]["ETH_USD"]["preset"] == "swing-aggressive"


def test_strategy_change_survives_reload(config_loader_mod, monkeypatch):
    """Watchlist strategy edits must not vanish after process reload (deploy)."""
    cl, volume_cfg, _ = config_loader_mod
    cl.save_config(
        {
            "version": 1,
            "defaults": {"preset": "swing"},
            "presets": {},
            "strategy_rules": {},
            "coins": {"DOT_USD": {"preset": "scalp-conservative", "overrides": {}}},
        }
    )

    cfg = cl.load_config()
    cfg.setdefault("coins", {})["DOT_USD"] = {
        "preset": "swing-aggressive",
        "overrides": {},
    }
    cl.save_config(cfg)

    # Backend recreate: new module load, same volume file
    cl2 = _load_config_loader(monkeypatch, volume_cfg)
    again = cl2.load_config()
    assert again["coins"]["DOT_USD"]["preset"] == "swing-aggressive"
