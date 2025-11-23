import json
from pathlib import Path
from copy import deepcopy
from typing import Dict, Any, Optional, Tuple

CONFIG_PATH = Path("trading_config.json")

_DEFAULT_CONFIG = {
    "version": 1,
    "defaults": {
        "timeframe": "4h",
        "preset": "swing",
        "alert_cooldown_minutes": 5,
        "alert_min_price_change_pct": 1.0
    },
    "presets": {
        "swing":   {
            "RSI_PERIOD":14, "RSI_BUY":38, "RSI_SELL":68, "MA50":50, "EMA10":9,
            "MA10W":70, "ATR":14, "VOL":10,
            "ALERT_COOLDOWN_MINUTES": 5,
            "ALERT_MIN_PRICE_CHANGE_PCT": 1.0
        },
        "intraday":{
            "RSI_PERIOD":10, "RSI_BUY":42, "RSI_SELL":65, "MA50":25, "EMA10":7,
            "MA10W":30, "ATR":10, "VOL":20,
            "ALERT_COOLDOWN_MINUTES": 3,
            "ALERT_MIN_PRICE_CHANGE_PCT": 0.8
        },
        "scalp":   {
            "RSI_PERIOD":7,  "RSI_BUY":45, "RSI_SELL":60, "MA50":20, "EMA10":5,
            "MA10W":15, "ATR":7,  "VOL":15,
            "ALERT_COOLDOWN_MINUTES": 2,
            "ALERT_MIN_PRICE_CHANGE_PCT": 0.5
        }
    },
    "coins": {}
}

NUM_FIELDS = {"RSI_PERIOD","RSI_BUY","RSI_SELL","MA50","EMA10","MA10W","ATR","VOL"}

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(_DEFAULT_CONFIG, indent=2))
        return deepcopy(_DEFAULT_CONFIG)
    return json.loads(CONFIG_PATH.read_text())

def validate_preset(preset: Dict[str, Any]) -> Tuple[bool, str]:
    for k in NUM_FIELDS:
        if k not in preset:
            return False, f"Missing field '{k}' in preset"
        v = preset[k]
        if not isinstance(v, (int, float)):
            return False, f"Field '{k}' must be number"
        if k in {"RSI_BUY","RSI_SELL"} and not (0 <= v <= 100):
            return False, f"Field '{k}' must be in 0..100"
        if v < 0:
            return False, f"Field '{k}' must be >= 0"
    return True, ""

def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

def resolve_params(symbol: str, inline_overrides: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    cfg = load_config()
    out: Dict[str, Any] = {}
    # 1 defaults
    out["TIMEFRAME"] = cfg.get("defaults",{}).get("timeframe","4h")
    sys_preset = cfg.get("defaults",{}).get("preset")
    # 2 preset por defecto
    if sys_preset and sys_preset in cfg.get("presets", {}):
        out.update(cfg["presets"][sys_preset])
    # 3 preset por moneda
    coin_cfg = cfg.get("coins", {}).get(symbol, {})
    coin_preset = coin_cfg.get("preset", sys_preset)
    if coin_preset and coin_preset in cfg.get("presets", {}):
        out.update(cfg["presets"][coin_preset])
    # 4 overrides por moneda
    out.update(coin_cfg.get("overrides", {}))
    # 5 overrides runtime
    if inline_overrides:
        out.update(inline_overrides)
    return out


def get_alert_thresholds(symbol: str, risk_mode: Optional[str] = None) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (min_price_change_pct, cooldown_minutes) for a symbol/strategy.
    Values are resolved in the following order:
        1. Global defaults
        2. Strategy/preset defaults
        3. Coin overrides (including preset strings like "swing-conservative")
    """
    cfg = load_config()
    defaults = cfg.get("defaults", {})
    default_cooldown = defaults.get("alert_cooldown_minutes")
    default_min_pct = defaults.get("alert_min_price_change_pct")

    coins_cfg = cfg.get("coins", {})
    coin_cfg = coins_cfg.get(symbol, {})
    preset_name = coin_cfg.get("preset") or defaults.get("preset")

    preset_cooldown = default_cooldown
    preset_min_pct = default_min_pct

    if preset_name:
        preset_key = preset_name.split("-")[0]  # remove risk suffix if present
        preset_cfg = cfg.get("presets", {}).get(preset_key, {})
        preset_cooldown = preset_cfg.get("ALERT_COOLDOWN_MINUTES", preset_cooldown)
        preset_min_pct = preset_cfg.get("ALERT_MIN_PRICE_CHANGE_PCT", preset_min_pct)

    overrides = coin_cfg.get("overrides", {})
    cooldown = overrides.get("ALERT_COOLDOWN_MINUTES", preset_cooldown)
    min_pct = overrides.get("ALERT_MIN_PRICE_CHANGE_PCT", preset_min_pct)

    return min_pct, cooldown
