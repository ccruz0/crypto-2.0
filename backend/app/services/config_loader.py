import json
import os
from pathlib import Path
from copy import deepcopy
from typing import Dict, Any, Optional, Tuple

# Determine config file path: use absolute path based on app root
# In container: /app/trading_config.json
# In local dev: backend/trading_config.json (relative to project root)
# Try multiple locations for robustness
_app_root = Path(__file__).parent.parent.parent  # backend/app/services -> backend/
_possible_paths = [
    Path("/app/trading_config.json"),  # Container absolute path
    _app_root / "trading_config.json",  # Local dev: backend/trading_config.json
    Path("trading_config.json"),  # Current working directory (fallback)
]

CONFIG_PATH = None
for path in _possible_paths:
    if path.exists():
        CONFIG_PATH = path
        break

if CONFIG_PATH is None:
    # Default to app root if file doesn't exist yet
    CONFIG_PATH = _app_root / "trading_config.json"
    # But if we're in container, prefer /app
    if Path("/app").exists():
        CONFIG_PATH = Path("/app/trading_config.json")

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

def _normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize config to ensure strategy_rules is the single source of truth.
    
    If strategy_rules exists, use it.
    If only legacy presets exists, migrate it to strategy_rules format.
    If neither exists, create default strategy_rules to ensure consistency.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Default strategy rules structure (used for migration and initialization)
    default_strategy_rules = {
        "swing": {
            "notificationProfile": "swing",
            "rules": {
                "Conservative": {
                    "rsi": {"buyBelow": 40, "sellAbove": 70},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                    "sl": {"atrMult": 1.5},
                    "tp": {"rr": 1.5},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 45, "sellAbove": 68},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                    "sl": {"atrMult": 1.0},
                    "tp": {"rr": 1.2},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                }
            }
        },
        "intraday": {
            "notificationProfile": "intraday",
            "rules": {
                "Conservative": {
                    "rsi": {"buyBelow": 45, "sellAbove": 70},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": False},
                    "sl": {"atrMult": 1.0},
                    "tp": {"rr": 1.2},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 50, "sellAbove": 65},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": False},
                    "sl": {"atrMult": 0.8},
                    "tp": {"rr": 1.0},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                }
            }
        },
        "scalp": {
            "notificationProfile": "scalp",
            "rules": {
                "Conservative": {
                    "rsi": {"buyBelow": 50, "sellAbove": 70},
                    "maChecks": {"ema10": True, "ma50": False, "ma200": False},
                    "sl": {"pct": 0.5},
                    "tp": {"pct": 0.8},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 55, "sellAbove": 65},
                    "maChecks": {"ema10": True, "ma50": False, "ma200": False},
                    "sl": {"pct": 0.35},
                    "tp": {"pct": 0.5},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 5.0,
                }
            }
        }
    }
    
    # If strategy_rules already exists and is not empty, return as-is
    if "strategy_rules" in cfg and cfg["strategy_rules"]:
        return cfg
    
    # If no strategy_rules but presets exists, migrate
    if "presets" in cfg and cfg["presets"]:
        logger.info("Migrating legacy presets to strategy_rules format")
        
        # Check if presets already has the new format (with rules structure)
        migrated_rules = {}
        
        for preset_key, preset_data in cfg["presets"].items():
            if isinstance(preset_data, dict) and "rules" in preset_data:
                # Already in new format, use it (preserves custom presets)
                migrated_rules[preset_key] = preset_data
                logger.debug(f"Preserved preset '{preset_key}' (already in new format)")
            else:
                # Legacy format
                if preset_key in default_strategy_rules:
                    # Known preset: use default structure
                    migrated_rules[preset_key] = default_strategy_rules[preset_key]
                    logger.debug(f"Migrated known preset '{preset_key}' using defaults")
                else:
                    # Custom preset in legacy format: create basic structure to preserve it
                    # We can't reliably convert old format, but we preserve the preset name
                    # with default values to avoid data loss
                    logger.warning(
                        f"Custom preset '{preset_key}' in legacy format detected. "
                        f"Creating basic structure with defaults (legacy values cannot be automatically converted)."
                    )
                    # Create a basic structure similar to default presets
                    # Use 'swing' as template since it's the most conservative
                    migrated_rules[preset_key] = {
                        "notificationProfile": preset_key.lower() if preset_key.lower() in ["swing", "intraday", "scalp"] else "swing",
                        "rules": {
                            "Conservative": {
                                "rsi": {"buyBelow": 40, "sellAbove": 70},
                                "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                                "sl": {"atrMult": 1.5},
                                "tp": {"rr": 1.5},
                                "volumeMinRatio": 0.5,
                                "minPriceChangePct": 1.0,
                                "alertCooldownMinutes": 5.0,
                            },
                            "Aggressive": {
                                "rsi": {"buyBelow": 45, "sellAbove": 68},
                                "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                                "sl": {"atrMult": 1.0},
                                "tp": {"rr": 1.2},
                                "volumeMinRatio": 0.5,
                                "minPriceChangePct": 1.0,
                                "alertCooldownMinutes": 5.0,
                            }
                        }
                    }
                    logger.info(f"Created basic structure for custom preset '{preset_key}' (user should review and update values)")
        
        # If we found any presets with rules structure, use them
        if migrated_rules:
            # Always include default presets to ensure all standard presets exist
            # Merge defaults with migrated rules (migrated rules take precedence)
            final_rules = {**default_strategy_rules, **migrated_rules}
            cfg["strategy_rules"] = final_rules
            custom_count = len([k for k in migrated_rules if k not in default_strategy_rules])
            if custom_count > 0:
                logger.info(f"Migrated {len(migrated_rules)} presets to strategy_rules (including {custom_count} custom presets with default values)")
            else:
                logger.info(f"Migrated {len(migrated_rules)} presets to strategy_rules")
        else:
            # No rules structure found, use defaults
            cfg["strategy_rules"] = default_strategy_rules
            logger.info("No rules structure in presets, using default strategy_rules")
    else:
        # Neither strategy_rules nor presets exists (or presets is empty)
        # Create default strategy_rules to ensure consistency
        logger.warning("Config has neither strategy_rules nor presets. Creating default strategy_rules to ensure consistency.")
        cfg["strategy_rules"] = default_strategy_rules
    
    return cfg


def load_config() -> Dict[str, Any]:
    import logging
    logger = logging.getLogger(__name__)
    
    # Log config path at first load
    if not hasattr(load_config, "_path_logged"):
        logger.info(f"Config file path: {CONFIG_PATH.absolute()}")
        load_config._path_logged = True
    
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(_DEFAULT_CONFIG, indent=2))
        normalized = _normalize_config(deepcopy(_DEFAULT_CONFIG))
        return normalized
    
    cfg = json.loads(CONFIG_PATH.read_text())
    return _normalize_config(cfg)

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
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Normalize config before saving to ensure strategy_rules exists
        cfg = _normalize_config(cfg)
        
        # Ensure strategy_rules is always present
        if "strategy_rules" not in cfg or not cfg["strategy_rules"]:
            logger.warning("save_config: No strategy_rules after normalization, this should not happen")
            # This should not happen after our fix, but if it does, re-normalize to create defaults
            # Re-run normalization which will create default strategy_rules if missing
            cfg = _normalize_config(cfg)
            if "strategy_rules" not in cfg or not cfg["strategy_rules"]:
                # If still missing after re-normalization, this is a critical error
                logger.error("save_config: strategy_rules still missing after re-normalization - this is a critical error")
                raise ValueError("strategy_rules is missing and could not be created")
        
        # Log volumeMinRatio values for each preset/riskMode
        strategy_rules = cfg.get("strategy_rules", {})
        if strategy_rules:
            for preset_name, preset_data in strategy_rules.items():
                if isinstance(preset_data, dict) and "rules" in preset_data:
                    for risk_mode, rules in preset_data.get("rules", {}).items():
                        if isinstance(rules, dict):
                            vol_ratio = rules.get("volumeMinRatio")
                            logger.info(f"[VOLUME] Saving {preset_name}/{risk_mode} volumeMinRatio={vol_ratio}")
        
        # Write config to file
        try:
            config_json = json.dumps(cfg, indent=2)
            CONFIG_PATH.write_text(config_json)
            logger.debug(f"Config saved to {CONFIG_PATH.absolute()}")
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to write config file to {CONFIG_PATH.absolute()}: {e}", exc_info=True)
            raise
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize config to JSON: {e}", exc_info=True)
            raise
    
    except Exception as e:
        logger.error(f"save_config failed: {e}", exc_info=True)
        raise

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


def get_strategy_rules(preset_name: str, risk_mode: str = "Conservative") -> Dict[str, Any]:
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
    
    Args:
        preset_name: Strategy preset name (e.g., "swing", "intraday", "scalp")
        risk_mode: Risk mode ("Conservative" or "Aggressive")
    
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
            # Return rules in expected format
            return {
                "rsi": {
                    "buyBelow": rules.get("rsi", {}).get("buyBelow") if isinstance(rules.get("rsi"), dict) else None,
                    "sellAbove": rules.get("rsi", {}).get("sellAbove") if isinstance(rules.get("rsi"), dict) else None,
                },
                "maChecks": rules.get("maChecks", {}),
                "volumeMinRatio": rules.get("volumeMinRatio"),
                "minPriceChangePct": rules.get("minPriceChangePct"),
                "alertCooldownMinutes": rules.get("alertCooldownMinutes"),
            }
    
    # Fallback to old format or defaults
    return {
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
