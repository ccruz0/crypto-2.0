"""Un bloqueo por filtro de regimen NO es un error del exchange.

Caso real (23-ago-2026): tres bloqueos correctos de cortos (DOT, ALGO, SUI)
por la regla price<MA200 (PR #540) llegaron a Telegram como
"ORDER FAILED / EXCHANGE_ERROR_UNKNOWN / Motivo: Exchange Error Unknown".
Carlos abrio la manana creyendo que el sistema estaba roto.

Causa raiz: classify_system_core_error solo reconocia el prefijo
`system_core_`; los filtros de regimen se llaman `short_regime_*` y
`long_btc_regime_*`, asi que caian al default terminal del exchange.

Consecuencia peor que el susto: un fallo REAL del exchange (saldo, API caida,
simbolo suspendido) era indistinguible de un bloqueo correcto.

Ver claude/atp-ordenes-fallando-24ago-veredicto.md en el proyecto Hilovivo.
"""

from app.utils.decision_reason import (
    ReasonCode,
    classify_exchange_error,
    classify_system_core_error,
    format_order_failed_telegram,
    reason_code_es_label,
)
from app.utils.guardrail_messages import (
    is_guardrail_family_reason,
    order_failed_store_message,
)

REALES = [
    "short_regime_price_above_ma200 price=0.9258 ma200=0.81795",
    "short_regime_price_above_ma200 price=0.09328 ma200=0.084435",
    "short_regime_price_above_ma200 price=0.83662 ma200=0.725871",
]


def test_los_tres_bloqueos_reales_no_son_error_de_exchange():
    for err in REALES:
        code = classify_exchange_error(err)
        assert code == ReasonCode.REGIME_FILTER_BLOCKED.value, err
        assert code != ReasonCode.EXCHANGE_ERROR_UNKNOWN.value


def test_filtro_largos_btc_tambien_clasifica():
    err = "long_btc_regime_btc_below_ma200 btc_price=60000 btc_ma200=69000"
    assert classify_exchange_error(err) == ReasonCode.REGIME_FILTER_BLOCKED.value


def test_variantes_fail_closed_del_filtro():
    for err in (
        "short_regime_ma200_unavailable symbol=DOT_USD",
        "short_regime_price_unavailable symbol=DOT_USD",
        "long_btc_regime_ma200_unavailable",
        "long_btc_regime_price_unavailable",
    ):
        assert classify_exchange_error(err) == ReasonCode.REGIME_FILTER_BLOCKED.value, err


def test_classify_system_core_error_reconoce_regimen():
    assert classify_system_core_error(REALES[0]) == ReasonCode.REGIME_FILTER_BLOCKED.value


def test_pertenece_a_la_familia_guardrail():
    assert is_guardrail_family_reason(ReasonCode.REGIME_FILTER_BLOCKED.value)
    assert is_guardrail_family_reason("", REALES[0])


def test_mensaje_telegram_usa_escudo_y_no_dice_order_failed():
    msg = format_order_failed_telegram(
        symbol="DOT_USD",
        side="SELL",
        error_msg=REALES[0],
        reason_code=ReasonCode.REGIME_FILTER_BLOCKED.value,
    )
    assert "ORDER FAILED" not in msg
    assert "ORDEN BLOQUEADA POR REGLA PROPIA" in msg
    assert "Exchange Error Unknown" not in msg
    assert "MA200" in msg
    assert "short_regime_price_above_ma200" in msg


def test_un_error_real_de_exchange_sigue_diciendo_order_failed():
    """Control positivo: el arreglo NO puede silenciar fallos de verdad."""
    for err, esperado in (
        ("Insufficient funds for order", ReasonCode.INSUFFICIENT_FUNDS.value),
        ("Order REJECTED by exchange", ReasonCode.EXCHANGE_REJECTED.value),
        ("Something totally unmapped happened", ReasonCode.EXCHANGE_ERROR_UNKNOWN.value),
    ):
        code = classify_exchange_error(err)
        assert code == esperado, (err, code)
        msg = format_order_failed_telegram(
            symbol="BTC_USD", side="BUY", error_msg=err, reason_code=code
        )
        assert "ORDER FAILED" in msg, err
        assert "ORDEN BLOQUEADA" not in msg, err


def test_mensaje_plano_de_bd_tambien_distingue():
    plano = order_failed_store_message(
        "DOT_USD",
        "SELL",
        REALES[0],
        ReasonCode.REGIME_FILTER_BLOCKED.value,
        display_reason="Filtro de regimen",
    )
    assert "ORDEN BLOQUEADA" in plano
    assert "ORDER FAILED" not in plano


def test_etiqueta_es_no_culpa_al_exchange():
    label = reason_code_es_label(ReasonCode.REGIME_FILTER_BLOCKED.value, REALES[0])
    assert "no es un error del exchange" in label.lower()
    assert "Error desconocido" not in label
