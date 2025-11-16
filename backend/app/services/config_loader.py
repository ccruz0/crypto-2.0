import json
from pathlib import Path
from copy import deepcopy
from typing import Dict, Any, Optional, Tuple

CONFIG_PATH = Path("trading_config.json")

_DEFAULT_CONFIG = {
    "version": 1,
    "defaults": {"timeframe": "4h", "preset": "swing"},
    "presets": {
        "swing":   { "RSI_PERIOD":14, "RSI_BUY":38, "RSI_SELL":68, "MA50":50, "EMA10":9,  "MA10W":70, "ATR":14, "VOL":10 },
        "intraday":{ "RSI_PERIOD":10, "RSI_BUY":42, "RSI_SELL":65, "MA50":25, "EMA10":7,  "MA10W":30, "ATR":10, "VOL":20 },
        "scalp":   { "RSI_PERIOD":7,  "RSI_BUY":45, "RSI_SELL":60, "MA50":20, "EMA10":5,  "MA10W":15, "ATR":7,  "VOL":15 }
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
