from fastapi import APIRouter, HTTPException
from typing import Any, Dict, Optional
import logging

from app.database import SessionLocal
from app.models.trade_signal import TradeSignal, PresetEnum, RiskProfileEnum
from app.models.watchlist import WatchlistItem
from app.services.config_loader import load_config, save_config, validate_preset, resolve_params

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])


def _log_volume_min_ratio(prefix: str, cfg: Dict[str, Any]) -> None:
    """
    Helper function to log volumeMinRatio values from config.
    
    Args:
        prefix: Log prefix (e.g., "GET" or "PUT")
        cfg: Config dictionary containing strategy_rules
    """
    strategy_rules = cfg.get("strategy_rules", {})
    for preset_name, preset_data in strategy_rules.items():
        if isinstance(preset_data, dict) and "rules" in preset_data:
            for risk_mode, rules in preset_data.get("rules", {}).items():
                if isinstance(rules, dict):
                    vol_ratio = rules.get("volumeMinRatio")
                    logger.info(f"[VOLUME] {prefix} {preset_name}/{risk_mode} volumeMinRatio={vol_ratio}")


@router.get("/config")
def get_config() -> Dict[str, Any]:
    cfg = load_config()
    _log_volume_min_ratio("GET", cfg)
    return cfg

@router.put("/config")
def put_config(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    SOURCE OF TRUTH: Save trading configuration to trading_config.json
    
    This endpoint is called by frontend when user saves changes in Signal Configuration tab.
    The config is stored in trading_config.json under "strategy_rules" key, which is then
    read by:
    1. Backend alert logic (get_strategy_rules() -> should_trigger_buy_signal())
    2. Frontend UI (Settings description, tooltip via presetsConfig state)
    
    Flow:
    1. User changes parameters in Signal Configuration tab (frontend)
    2. Frontend calls saveTradingConfig() -> this endpoint
    3. Backend merges into trading_config.json under "strategy_rules"
    4. Backend alert logic reads from same file via get_strategy_rules()
    5. Frontend reloads config and updates presetsConfig state
    6. Settings description and tooltip regenerate from updated config
    
    New format (from dashboard Signal Configuration):
    {
        "strategy_rules": {
            "swing": {
                "notificationProfile": "swing",
                "rules": {
                    "Conservative": {
                        "rsi": {"buyBelow": 40, "sellAbove": 70},
                        "maChecks": {"ema10": true, "ma50": true, "ma200": true},
                        "volumeMinRatio": 0.5,
                        "minPriceChangePct": 1.0,
                        "alertCooldownMinutes": 5.0
                    },
                    "Aggressive": {...}
                }
            },
            ...
        }
    }
    
    Old format (legacy):
    {
        "presets": {
            "swing": {
                "RSI_PERIOD": 14,
                "RSI_BUY": 38,
                "RSI_SELL": 68,
                ...
            }
        }
    }
    """
    # Merge with existing config to preserve coins and defaults
    existing_cfg = load_config()
    
    # Update presets from new_cfg
    new_presets = new_cfg.get("presets", {})
    for preset_name, preset_data in new_presets.items():
        # If new format (has "rules"), save as-is
        if "rules" in preset_data:
            existing_cfg.setdefault("presets", {})[preset_name] = preset_data
        else:
            # Old format: validate and save
            ok, msg = validate_preset(preset_data)
            if not ok:
                raise HTTPException(status_code=400, detail=f"Preset '{preset_name}': {msg}")
            existing_cfg.setdefault("presets", {})[preset_name] = preset_data
    
    # SOURCE OF TRUTH: Update strategy_rules (new structure from Signal Configuration UI)
    # This is the canonical location where preset config is stored
    if "strategy_rules" in new_cfg:
        _log_volume_min_ratio("PUT incoming", new_cfg)
        existing_cfg["strategy_rules"] = new_cfg["strategy_rules"]
    else:
        logger.warning("PUT /config: No strategy_rules in incoming config!")

    # Update defaults if provided
    if "defaults" in new_cfg:
        existing_cfg["defaults"] = {**existing_cfg.get("defaults", {}), **new_cfg["defaults"]}
    
    # Update coins if provided (merge, don't replace)
    if "coins" in new_cfg:
        existing_cfg.setdefault("coins", {}).update(new_cfg["coins"])
    
    # Save config (save_config will normalize and ensure strategy_rules exists)
    save_config(existing_cfg)
    
    return {"ok": True}

@router.put("/presets/{name}")
def upsert_preset(name: str, preset: Dict[str, Any]) -> Dict[str, Any]:
    ok, msg = validate_preset(preset)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    cfg = load_config()
    cfg.setdefault("presets", {})[name] = preset
    save_config(cfg)
    return {"ok": True}

@router.delete("/presets/{name}")
def delete_preset(name: str) -> Dict[str, Any]:
    cfg = load_config()
    in_use = [s for s, c in cfg.get("coins", {}).items() if c.get("preset") == name]
    if in_use:
        raise HTTPException(status_code=409, detail={"message": "Preset in use", "symbols": in_use})
    if name in cfg.get("presets", {}):
        del cfg["presets"][name]
        save_config(cfg)
    return {"ok": True}

def _parse_preset_strings(preset: Optional[str]) -> tuple[Optional[PresetEnum], Optional[RiskProfileEnum]]:
    """
    Convert a dashboard preset string like 'scalp-conservative' into
    (PresetEnum.SCALP, RiskProfileEnum.CONSERVATIVE).
    """
    if not preset:
        return None, None

    normalized = preset.lower()
    if "-" in normalized:
        base, suffix = normalized.split("-", 1)
    else:
        base, suffix = normalized, None

    preset_enum: Optional[PresetEnum]
    try:
        preset_enum = PresetEnum(base)
    except ValueError:
        preset_enum = None

    risk_enum: Optional[RiskProfileEnum] = None
    if suffix:
        normalized_suffix = suffix.lower()
        if normalized_suffix in {"conservative", "conservadora"}:
            risk_enum = RiskProfileEnum.CONSERVATIVE
        elif normalized_suffix in {"aggressive", "agresiva"}:
            risk_enum = RiskProfileEnum.AGGRESSIVE

    return preset_enum, risk_enum


def _sync_trade_signal(symbol: str, preset: Optional[str]) -> None:
    """Keep trade_signals table aligned with dashboard preset selections."""
    session = SessionLocal()
    symbol_key = (symbol or "").upper()
    try:
        trade_signal = session.query(TradeSignal).filter(TradeSignal.symbol == symbol_key).first()
        if not trade_signal:
            return

        desired_preset, desired_risk = _parse_preset_strings(preset)

        if desired_risk is None:
            # Fallback to watchlist sl_tp_mode if preset string lacks explicit risk part
            watchlist_item = (
                session.query(WatchlistItem)
                .filter(WatchlistItem.symbol == symbol_key)
                .first()
            )
            if watchlist_item:
                mode = (watchlist_item.sl_tp_mode or "").lower()
                if mode in {"aggressive", "agresiva"}:
                    desired_risk = RiskProfileEnum.AGGRESSIVE
                elif mode in {"conservative", "conservadora"}:
                    desired_risk = RiskProfileEnum.CONSERVATIVE

        updated = False
        if desired_preset and trade_signal.preset != desired_preset:
            trade_signal.preset = desired_preset
            updated = True
        if desired_risk and trade_signal.sl_profile != desired_risk:
            trade_signal.sl_profile = desired_risk
            updated = True

        if updated:
            session.commit()
            logger.info("Synced TradeSignal for %s to %s/%s", symbol_key, desired_preset, desired_risk)
        else:
            session.rollback()
    except Exception as exc:  # pragma: no cover - defensive
        session.rollback()
        logger.warning("Failed to sync TradeSignal for %s: %s", symbol_key, exc)
    finally:
        session.close()


@router.put("/coins/{symbol}")
def upsert_coin(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    preset = payload.get("preset")
    overrides = payload.get("overrides", {})
    if preset and preset not in cfg.get("presets", {}):
        raise HTTPException(status_code=400, detail=f"Unknown preset '{preset}'")
    cfg.setdefault("coins", {})[symbol] = {"preset": preset, "overrides": overrides}
    save_config(cfg)

    # Keep trade_signals table aligned with dashboard selections
    _sync_trade_signal(symbol, preset)

    return {"ok": True}

@router.get("/params/{symbol}")
def get_params(symbol: str) -> Dict[str, Any]:
    return resolve_params(symbol)
