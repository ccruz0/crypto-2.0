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
        
        # Support both old format (direct keys) and new format (rules structure)
        if "rules" in preset_cfg:
            # New format: check rules for risk mode
            risk_key = risk_mode.lower().capitalize() if risk_mode else "Conservative"
            if risk_key not in ["Conservative", "Aggressive"]:
                risk_key = "Conservative"
            rules = preset_cfg.get("rules", {}).get(risk_key, {})
            preset_cooldown = rules.get("alertCooldownMinutes", rules.get("alert_cooldown_minutes", preset_cooldown))
            preset_min_pct = rules.get("minPriceChangePct", rules.get("min_price_change_pct", preset_min_pct))
        else:
            # Old format: direct keys
            preset_cooldown = preset_cfg.get("ALERT_COOLDOWN_MINUTES", preset_cooldown)
            preset_min_pct = preset_cfg.get("ALERT_MIN_PRICE_CHANGE_PCT", preset_min_pct)

    overrides = coin_cfg.get("overrides", {})
    cooldown = overrides.get("ALERT_COOLDOWN_MINUTES", preset_cooldown)
    min_pct = overrides.get("ALERT_MIN_PRICE_CHANGE_PCT", preset_min_pct)

    return min_pct, cooldown


def get_strategy_rules(preset_name: str, risk_mode: str = "Conservative", symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    SOURCE OF TRUTH: Get strategy rules from trading_config.json
    
    This is the canonical function that reads preset configuration used by:
    1. Backend alert generation logic (should_trigger_buy_signal, etc.)
    2. Frontend Signal Configuration UI (via /api/config GET)
    3. Settings description text (generated from same config)
    4. Tooltip/Infobox (generated from same config)
    
    The config is stored in trading_config.json under "strategy_rules" key:
    {
        "strategy_rules": {
            "swing": {
                "notificationProfile": "swing",
                "rules": {
                    "Conservative": {
                        "rsi": {"buyBelow": 40, "sellAbove": 70},
                        "maChecks": {"ema10": true, "ma50": true, "ma200": true},
                        "volumeMinRatio": 0.5,
                        ...
                    },
                    "Aggressive": {...}
                }
            },
            ...
        }
    }
    
    When frontend saves config via /api/config PUT, it updates "strategy_rules" in trading_config.json.
    This function then reads from that same structure, ensuring consistency.
    
    Supports both new format (rules structure from dashboard) and old format (legacy direct keys).
    
    Per-symbol overrides: If symbol is provided, applies overrides from "coins" section.
    Example: {"coins": {"ALGO_USDT": {"overrides": {"volumeMinRatio": 0.30}}}}
    
    Args:
        preset_name: Strategy preset name (e.g., "swing", "intraday", "scalp")
        risk_mode: Risk mode ("Conservative" or "Aggressive")
        symbol: Optional trading symbol to apply per-symbol overrides
    
    Returns:
        Dict with rules: {
            "rsi": {"buyBelow": int, "sellAbove": int},
            "maChecks": {"ema10": bool, "ma50": bool, "ma200": bool},
            "volumeMinRatio": float,
            ...
        }
    """
    cfg = load_config()
    preset_key = preset_name.lower()  # Normalize to lowercase
    # SOURCE OF TRUTH: Prefer strategy_rules structure (dashboard source of truth)
    # This is where frontend saves config when user changes Signal Configuration
    strategy_rules_cfg = cfg.get("strategy_rules", {})
    preset_cfg = strategy_rules_cfg.get(preset_key) or cfg.get("presets", {}).get(preset_key, {})
    
    # Normalize risk_mode
    risk_key = risk_mode.capitalize() if risk_mode else "Conservative"
    if risk_key not in ["Conservative", "Aggressive"]:
        risk_key = "Conservative"
    
    # Check if new format (has "rules" structure)
    if "rules" in preset_cfg:
        rules = preset_cfg.get("rules", {}).get(risk_key, {})
        if rules:
            # Build base rules dict
            base_rules = {
                "rsi": {
                    "buyBelow": rules.get("rsi", {}).get("buyBelow") if isinstance(rules.get("rsi"), dict) else None,
                    "sellAbove": rules.get("rsi", {}).get("sellAbove") if isinstance(rules.get("rsi"), dict) else None,
                },
                "maChecks": rules.get("maChecks", {}),
                "volumeMinRatio": rules.get("volumeMinRatio"),
                "minPriceChangePct": rules.get("minPriceChangePct"),
                "alertCooldownMinutes": rules.get("alertCooldownMinutes"),
            }
            
            # CRITICAL FIX: Add logging for debugging persistence
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"[STRATEGY_PERSISTENCE] get_strategy_rules({preset_name}, {risk_mode}, {symbol}): "
                        f"maChecks={base_rules.get('maChecks')}, rsi={base_rules.get('rsi')}, "
                        f"volumeMinRatio={base_rules.get('volumeMinRatio')}")
            
            # Apply per-symbol overrides if symbol is provided
            if symbol:
                coins_cfg = cfg.get("coins", {})
                coin_cfg = coins_cfg.get(symbol, {})
                overrides = coin_cfg.get("overrides", {})
                if overrides:
                    # Apply overrides (only override keys that exist in base_rules)
                    if "volumeMinRatio" in overrides:
                        base_rules["volumeMinRatio"] = overrides["volumeMinRatio"]
                    if "minPriceChangePct" in overrides:
                        base_rules["minPriceChangePct"] = overrides["minPriceChangePct"]
                    if "alertCooldownMinutes" in overrides:
                        base_rules["alertCooldownMinutes"] = overrides["alertCooldownMinutes"]
                    # RSI overrides (if provided as nested dict or flat keys)
                    if "rsi" in overrides and isinstance(overrides["rsi"], dict):
                        if "buyBelow" in overrides["rsi"]:
                            base_rules["rsi"]["buyBelow"] = overrides["rsi"]["buyBelow"]
                        if "sellAbove" in overrides["rsi"]:
                            base_rules["rsi"]["sellAbove"] = overrides["rsi"]["sellAbove"]
                    # CRITICAL FIX: Apply maChecks overrides from per-symbol config
                    if "maChecks" in overrides and isinstance(overrides["maChecks"], dict):
                        base_rules["maChecks"] = {**base_rules.get("maChecks", {}), **overrides["maChecks"]}
            
            return base_rules
    
    # Fallback to old format or defaults
    base_rules = {
        "rsi": {
            "buyBelow": preset_cfg.get("RSI_BUY"),
            "sellAbove": preset_cfg.get("RSI_SELL"),
        },
        "maChecks": {
            "ema10": True,  # Default behavior
            "ma50": True if preset_key in ["swing", "intraday"] else False,
            "ma200": True if preset_key == "swing" else False,
        },
        "volumeMinRatio": 0.5,  # Default
        "minPriceChangePct": preset_cfg.get("ALERT_MIN_PRICE_CHANGE_PCT", 1.0),
        "alertCooldownMinutes": preset_cfg.get("ALERT_COOLDOWN_MINUTES", 5),
    }
    
    # Apply per-symbol overrides if symbol is provided
    if symbol:
        coins_cfg = cfg.get("coins", {})
        coin_cfg = coins_cfg.get(symbol, {})
        overrides = coin_cfg.get("overrides", {})
        if overrides:
            if "volumeMinRatio" in overrides:
                base_rules["volumeMinRatio"] = overrides["volumeMinRatio"]
            if "minPriceChangePct" in overrides:
                base_rules["minPriceChangePct"] = overrides["minPriceChangePct"]
            if "alertCooldownMinutes" in overrides:
                base_rules["alertCooldownMinutes"] = overrides["alertCooldownMinutes"]
    
    return base_rules
