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
        "alert_cooldown_minutes": 0.1667,
        "alert_min_price_change_pct": 1.0
    },
    "presets": {
        "swing":   {
            "RSI_PERIOD":14, "RSI_BUY":38, "RSI_SELL":68, "MA50":50, "EMA10":9,
            "MA10W":70, "ATR":14, "VOL":10,
            "ALERT_COOLDOWN_MINUTES": 0.1667,
            "ALERT_MIN_PRICE_CHANGE_PCT": 1.0
        },
        "intraday":{
            "RSI_PERIOD":10, "RSI_BUY":42, "RSI_SELL":65, "MA50":25, "EMA10":7,
            "MA10W":30, "ATR":10, "VOL":20,
            "ALERT_COOLDOWN_MINUTES": 0.1667,
            "ALERT_MIN_PRICE_CHANGE_PCT": 0.8
        },
        "scalp":   {
            "RSI_PERIOD":7,  "RSI_BUY":45, "RSI_SELL":60, "MA50":20, "EMA10":5,
            "MA10W":15, "ATR":7,  "VOL":15,
            "ALERT_COOLDOWN_MINUTES": 0.1667,
            "ALERT_MIN_PRICE_CHANGE_PCT": 0.5
        }
    },
    "coins": {}
}

NUM_FIELDS = {"RSI_PERIOD","RSI_BUY","RSI_SELL","MA50","EMA10","MA10W","ATR","VOL"}

def _migrate_swing_conservative_defaults(rules: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migrate Swing Conservative rules from old defaults to new stricter defaults.
    Only updates if the config still matches old defaults (preserves user customizations).
    
    Old defaults:
    - rsi.buyBelow: 40 -> 30
    - volumeMinRatio: 0.5 -> 1.0
    - minPriceChangePct: 1.0 -> 3.0
    - sl.fallbackPct: missing -> 3.0 (if using percentage fallback)
    
    New gating parameters (added if missing):
    - trendFilters, rsiConfirmation, candleConfirmation, atr
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not isinstance(rules, dict):
        return rules
    
    # Check if this looks like old defaults (exact match)
    rsi = rules.get("rsi", {})
    old_rsi_buy = rsi.get("buyBelow") if isinstance(rsi, dict) else None
    old_volume = rules.get("volumeMinRatio")
    old_min_change = rules.get("minPriceChangePct")
    
    # Check if it matches old defaults exactly
    matches_old_defaults = (
        old_rsi_buy == 40 and
        old_volume == 0.5 and
        old_min_change == 1.0
    )
    
    updated = False
    migrated_rules = dict(rules)
    
    if matches_old_defaults:
        logger.info("Migrating Swing Conservative from old defaults to new stricter defaults")
        
        # Update RSI threshold
        if isinstance(rsi, dict):
            migrated_rsi = dict(rsi)
            migrated_rsi["buyBelow"] = 30
            migrated_rules["rsi"] = migrated_rsi
            updated = True
        
        # Update volume requirement
        migrated_rules["volumeMinRatio"] = 1.0
        updated = True
        
        # Update min price change
        migrated_rules["minPriceChangePct"] = 3.0
        updated = True
        
        # Add SL fallback percentage if SL config exists
        sl = migrated_rules.get("sl", {})
        if isinstance(sl, dict) and "atrMult" in sl and "fallbackPct" not in sl:
            migrated_sl = dict(sl)
            migrated_sl["fallbackPct"] = 3.0
            migrated_rules["sl"] = migrated_sl
            updated = True
    
    # Add new gating parameters if missing (regardless of whether we migrated old defaults)
    if "trendFilters" not in migrated_rules:
        migrated_rules["trendFilters"] = {
            "require_price_above_ma200": True,
            "require_ema10_above_ma50": True
        }
        updated = True
    
    if "rsiConfirmation" not in migrated_rules:
        migrated_rules["rsiConfirmation"] = {
            "require_rsi_cross_up": True,
            "rsi_cross_level": 30
        }
        updated = True
    
    if "candleConfirmation" not in migrated_rules:
        migrated_rules["candleConfirmation"] = {
            "require_close_above_ema10": True,
            "require_rsi_rising_n_candles": 2
        }
        updated = True
    
    if "atr" not in migrated_rules:
        migrated_rules["atr"] = {
            "period": 14,
            "multiplier_sl": 1.5,
            "multiplier_tp": None
        }
        updated = True
    
    if updated:
        logger.info("Swing Conservative migration completed (added new gating parameters)")
    
    return migrated_rules


def _normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize config to ensure strategy_rules is the single source of truth.
    
    If strategy_rules exists, use it.
    If only legacy presets exists, migrate it to strategy_rules format.
    If neither exists, create default strategy_rules to ensure consistency.
    
    Also migrates Swing Conservative from old defaults to new stricter defaults.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Default strategy rules structure (used for migration and initialization)
    default_strategy_rules = {
        "swing": {
            "notificationProfile": "swing",
            "rules": {
                "Conservative": {
                    "rsi": {"buyBelow": 30, "sellAbove": 70},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                    "sl": {"atrMult": 1.5, "fallbackPct": 3.0},
                    "tp": {"rr": 1.5},
                    "volumeMinRatio": 1.0,
                    "minPriceChangePct": 3.0,
                    "alertCooldownMinutes": 0.1667,
                    "trendFilters": {
                        "require_price_above_ma200": True,
                        "require_ema10_above_ma50": True
                    },
                    "rsiConfirmation": {
                        "require_rsi_cross_up": True,
                        "rsi_cross_level": 30
                    },
                    "candleConfirmation": {
                        "require_close_above_ema10": True,
                        "require_rsi_rising_n_candles": 2
                    },
                    "atr": {
                        "period": 14,
                        "multiplier_sl": 1.5,
                        "multiplier_tp": None
                    },
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 45, "sellAbove": 68},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                    "sl": {"atrMult": 1.0},
                    "tp": {"rr": 1.2},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 0.1667,
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
                    "alertCooldownMinutes": 0.1667,
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 50, "sellAbove": 65},
                    "maChecks": {"ema10": True, "ma50": True, "ma200": False},
                    "sl": {"atrMult": 0.8},
                    "tp": {"rr": 1.0},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 0.1667,
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
                    "alertCooldownMinutes": 0.1667,
                },
                "Aggressive": {
                    "rsi": {"buyBelow": 55, "sellAbove": 65},
                    "maChecks": {"ema10": True, "ma50": False, "ma200": False},
                    "sl": {"pct": 0.35},
                    "tp": {"pct": 0.5},
                    "volumeMinRatio": 0.5,
                    "minPriceChangePct": 1.0,
                    "alertCooldownMinutes": 0.1667,
                }
            }
        }
    }
    
    # If strategy_rules already exists and is not empty, migrate Swing Conservative defaults if needed
    if "strategy_rules" in cfg and cfg["strategy_rules"]:
        # Migrate Swing Conservative defaults if needed
        swing_preset = cfg["strategy_rules"].get("swing")
        if isinstance(swing_preset, dict) and "rules" in swing_preset:
            conservative_rules = swing_preset["rules"].get("Conservative")
            if isinstance(conservative_rules, dict):
                migrated = _migrate_swing_conservative_defaults(conservative_rules)
                if migrated != conservative_rules:
                    swing_preset["rules"]["Conservative"] = migrated
                    cfg["strategy_rules"]["swing"] = swing_preset
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
                                "alertCooldownMinutes": 0.1667,
                            },
                            "Aggressive": {
                                "rsi": {"buyBelow": 45, "sellAbove": 68},
                                "maChecks": {"ema10": True, "ma50": True, "ma200": True},
                                "sl": {"atrMult": 1.0},
                                "tp": {"rr": 1.2},
                                "volumeMinRatio": 0.5,
                                "minPriceChangePct": 1.0,
                                "alertCooldownMinutes": 0.1667,
                            }
                        }
                    }
                    logger.info(f"Created basic structure for custom preset '{preset_key}' (user should review and update values)")
        
        # If we found any presets with rules structure, use them
        if migrated_rules:
            # FIX: Deep merge at risk-mode level to preserve missing risk modes
            # Start with defaults, then merge migrated rules at preset level,
            # but merge rules at risk-mode level to preserve both Conservative and Aggressive
            final_rules = deepcopy(default_strategy_rules)
            
            for preset_key, migrated_preset in migrated_rules.items():
                if preset_key in final_rules:
                    # Known preset: deep merge at risk-mode level
                    default_preset = final_rules[preset_key]
                    if isinstance(migrated_preset, dict) and "rules" in migrated_preset:
                        # Merge notificationProfile if present
                        if "notificationProfile" in migrated_preset:
                            default_preset["notificationProfile"] = migrated_preset["notificationProfile"]
                        
                        # Deep merge rules at risk-mode level
                        # Start with default rules, then merge migrated rules
                        merged_rules = deepcopy(default_preset.get("rules", {}))
                        migrated_rules_dict = migrated_preset.get("rules", {})
                        
                        # Merge each risk mode individually
                        for risk_mode, migrated_risk_rules in migrated_rules_dict.items():
                            if isinstance(migrated_risk_rules, dict):
                                # Merge migrated rules into default rules for this risk mode
                                if risk_mode in merged_rules:
                                    merged_rules[risk_mode] = {**merged_rules[risk_mode], **migrated_risk_rules}
                                else:
                                    # New risk mode not in defaults, add it
                                    merged_rules[risk_mode] = migrated_risk_rules
                        
                        default_preset["rules"] = merged_rules
                        logger.debug(f"Deep merged preset '{preset_key}' at risk-mode level")
                    else:
                        # Invalid structure, use default
                        logger.warning(f"Preset '{preset_key}' in migrated_rules has invalid structure, using defaults")
                else:
                    # Custom preset not in defaults, add it as-is
                    final_rules[preset_key] = deepcopy(migrated_preset)
                    logger.debug(f"Added custom preset '{preset_key}' to final rules")
            
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
        # Create default config and normalize it
        normalized = _normalize_config(deepcopy(_DEFAULT_CONFIG))
        # Write the normalized version to disk to ensure consistency
        # This prevents repeated migrations on subsequent loads
        CONFIG_PATH.write_text(json.dumps(normalized, indent=2))
        logger.info("Created new config file with normalized structure (including strategy_rules)")
        return normalized
    
    cfg = json.loads(CONFIG_PATH.read_text())
    normalized = _normalize_config(cfg)
    return normalized

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

def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save config to disk after normalization.
    
    Returns:
        The normalized config that was actually saved to disk.
        This ensures callers can use the returned value to get the exact
        structure that was persisted, including any fields added by normalization.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Normalize config before saving to ensure strategy_rules exists
        # Make a copy to avoid modifying the input dict
        normalized_cfg = _normalize_config(deepcopy(cfg))
        
        # Ensure strategy_rules is always present
        if "strategy_rules" not in normalized_cfg or not normalized_cfg["strategy_rules"]:
            logger.warning("save_config: No strategy_rules after normalization, this should not happen")
            # This should not happen after our fix, but if it does, re-normalize to create defaults
            # Re-run normalization which will create default strategy_rules if missing
            normalized_cfg = _normalize_config(normalized_cfg)
            if "strategy_rules" not in normalized_cfg or not normalized_cfg["strategy_rules"]:
                # If still missing after re-normalization, this is a critical error
                logger.error("save_config: strategy_rules still missing after re-normalization - this is a critical error")
                raise ValueError("strategy_rules is missing and could not be created")
        
        # Log volumeMinRatio values for each preset/riskMode
        strategy_rules = normalized_cfg.get("strategy_rules", {})
        if strategy_rules:
            for preset_name, preset_data in strategy_rules.items():
                if isinstance(preset_data, dict) and "rules" in preset_data:
                    for risk_mode, rules in preset_data.get("rules", {}).items():
                        if isinstance(rules, dict):
                            vol_ratio = rules.get("volumeMinRatio")
                            logger.info(f"[VOLUME] Saving {preset_name}/{risk_mode} volumeMinRatio={vol_ratio}")
        
        # Write config to file
        try:
            config_json = json.dumps(normalized_cfg, indent=2)
            CONFIG_PATH.write_text(config_json)
            logger.debug(f"Config saved to {CONFIG_PATH.absolute()}")
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to write config file to {CONFIG_PATH.absolute()}: {e}", exc_info=True)
            raise
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize config to JSON: {e}", exc_info=True)
            raise
        
        # Return the normalized config that was actually saved
        return normalized_cfg
    
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
            # Return rules in expected format (including new gating parameters)
            result = {
                "rsi": {
                    "buyBelow": rules.get("rsi", {}).get("buyBelow") if isinstance(rules.get("rsi"), dict) else None,
                    "sellAbove": rules.get("rsi", {}).get("sellAbove") if isinstance(rules.get("rsi"), dict) else None,
                },
                "maChecks": rules.get("maChecks", {}),
                "volumeMinRatio": rules.get("volumeMinRatio"),
                "minPriceChangePct": rules.get("minPriceChangePct"),
                "alertCooldownMinutes": rules.get("alertCooldownMinutes"),
                "maxOrdersPerSymbolPerDay": rules.get("maxOrdersPerSymbolPerDay"),
                "sl": rules.get("sl", {}),
                "tp": rules.get("tp", {}),
                "trendFilters": rules.get("trendFilters", {}),
                "rsiConfirmation": rules.get("rsiConfirmation", {}),
                "candleConfirmation": rules.get("candleConfirmation", {}),
                "atr": rules.get("atr", {}),
            }
            return result
    
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
        "alertCooldownMinutes": preset_cfg.get("ALERT_COOLDOWN_MINUTES", 0.1667),
    }
