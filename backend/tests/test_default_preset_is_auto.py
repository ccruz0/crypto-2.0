"""El preset por defecto debe ser `auto`, no `swing`.

Motivo (decision de Carlos, 23-ago-2026): una moneda sin entrada explicita en
`coins` heredaba `defaults.preset` al habilitarse. Con "swing" empezaba a operar
bajo un perfil que nadie habia escrito en ningun sitio; con "auto" cae en la
banda `Learned`, que esta congelada con baseline y vigilada semanalmente.

Ver `claude/atp-sincronizacion-monedas.md` en el proyecto Hilovivo.
"""

from unittest.mock import patch

from app.services.config_loader import _DEFAULT_CONFIG
from app.services.strategy_profiles import (
    RiskApproach,
    StrategyType,
    resolve_strategy_profile,
)

# Las 17 monedas con trade_enabled=true en produccion el 23-ago-2026.
MONEDAS_OPERATIVAS = [
    "AAVE_USD", "AKT_USD", "ALGO_USD", "APT_USD", "ATOM_USD", "BCH_USD",
    "BONK_USD", "BTC_USD", "CRO_USD", "DGB_USD", "DOGE_USD", "DOT_USD",
    "HBAR_USD", "SOL_USD", "SUI_USD", "XLM_USD", "XRP",
]


def test_default_preset_es_auto():
    assert _DEFAULT_CONFIG["defaults"]["preset"] == "auto"


def test_moneda_sin_entrada_cae_en_auto_no_en_swing():
    """Sin entrada en `coins`, el fallback debe ser AUTO."""
    cfg = {"coins": {}, "defaults": {"preset": "auto"}}
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile("NUEVA_USD")
    assert strategy == StrategyType.AUTO
    assert approach == RiskApproach.CONSERVATIVE


def test_entrada_explicita_sigue_ganando_al_default():
    """El default no puede pisar un preset declarado por moneda."""
    cfg = {
        "coins": {"TON_USDT": {"preset": "swing-aggressive"}},
        "defaults": {"preset": "auto"},
    }
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        strategy, approach = resolve_strategy_profile("TON_USDT")
    assert strategy == StrategyType.SWING
    assert approach == RiskApproach.AGGRESSIVE


def test_las_17_operativas_resuelven_a_auto_con_entrada_propia():
    """Con entrada propia para las 17, ninguna depende del fallback cruzado."""
    cfg = {
        "coins": {sym: {"preset": "auto", "overrides": {}} for sym in MONEDAS_OPERATIVAS},
        "defaults": {"preset": "auto"},
    }
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        for sym in MONEDAS_OPERATIVAS:
            strategy, _ = resolve_strategy_profile(sym)
            assert strategy == StrategyType.AUTO, sym


def test_akt_apt_cro_no_dependen_del_fallback_cruzado():
    """Los tres que hoy resuelven prestado del par USDT deben tener entrada propia.

    Sin su entrada, y con las USDT marcadas inactivas, caerian al default;
    con el default en auto el resultado es el mismo, pero la resolucion deja
    de ser silenciosa.
    """
    cfg = {
        "coins": {
            "AKT_USD": {"preset": "auto"},
            "APT_USD": {"preset": "auto"},
            "CRO_USD": {"preset": "auto"},
        },
        "defaults": {"preset": "auto"},
    }
    with patch("app.services.strategy_profiles._load_config_cached", return_value=cfg):
        for sym in ("AKT_USD", "APT_USD", "CRO_USD"):
            strategy, _ = resolve_strategy_profile(sym)
            assert strategy == StrategyType.AUTO, sym
