from fastapi import APIRouter, HTTPException
from typing import Any, Dict
from app.services.config_loader import load_config, save_config, validate_preset, resolve_params

router = APIRouter(prefix="/api", tags=["config"])

@router.get("/config")
def get_config() -> Dict[str, Any]:
    return load_config()

@router.put("/config")
def put_config(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    # Validación básica de presets
    presets = new_cfg.get("presets", {})
    for name, preset in presets.items():
        ok, msg = validate_preset(preset)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Preset '{name}': {msg}")
    save_config(new_cfg)
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

@router.put("/coins/{symbol}")
def upsert_coin(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    preset = payload.get("preset")
    overrides = payload.get("overrides", {})
    if preset and preset not in cfg.get("presets", {}):
        raise HTTPException(status_code=400, detail=f"Unknown preset '{preset}'")
    cfg.setdefault("coins", {})[symbol] = {"preset": preset, "overrides": overrides}
    save_config(cfg)
    return {"ok": True}

@router.get("/params/{symbol}")
def get_params(symbol: str) -> Dict[str, Any]:
    return resolve_params(symbol)
