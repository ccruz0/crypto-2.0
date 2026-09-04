"""El barrido OCO debe rendirse tras N fallos, no reintentar para siempre.

Incidente del 4-sep-2026: una orden fantasma de BONK (STOP_LOSS 73817490102145811,
ACTIVE en la DB pero inexistente en el exchange) acumulo 196 intentos de
cancelacion en 20 minutos, uno cada ~5 s, con una alerta de Telegram por vuelta.

La causa de fondo vive en el broker, en fichero protegido por el Path Guard: el
400 se descarta antes de leer su cuerpo, asi que el detector de "ya no existe"
nunca puede acertar. Estos tests fijan el limite del dano: pase lo que pase con
esa causa, el bucle tiene que parar.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services import exchange_sync as es
from app.models.exchange_order import OrderStatusEnum


def _orphan(order_id="73817490102145811"):
    o = MagicMock()
    o.exchange_order_id = order_id
    o.status = OrderStatusEnum.ACTIVE
    o.order_role = "STOP_LOSS"
    o.order_type = "STOP_LOSS"
    o.symbol = "BONK_USD"
    o.oco_group_id = "oco_5755600494263839826_1788506000"
    o.parent_order_id = "5755600494263839826"
    return o


def _filled_sibling(order_id="73817490102145810"):
    s = MagicMock()
    s.exchange_order_id = order_id
    s.status = OrderStatusEnum.FILLED
    s.order_role = "TAKE_PROFIT"
    s.symbol = "BONK_USD"
    return s


def _service_with(orphan, filled):
    svc = es.ExchangeSyncService.__new__(es.ExchangeSyncService)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [orphan]
    return svc, db


def test_sweep_gives_up_after_max_failures():
    """Con la cancelacion fallando siempre, el barrido deja de intentarlo."""
    orphan, filled = _orphan(), _filled_sibling()
    svc, db = _service_with(orphan, filled)
    live = {str(orphan.exchange_order_id)}

    with patch.object(svc, "_find_oco_siblings", return_value=[filled]):
        with patch.object(svc, "_cancel_oco_sibling", return_value=False) as cancel:
            # Muchas mas vueltas que el tope: en produccion fueron 196.
            for _ in range(40):
                svc._sweep_orphaned_oco_siblings(db, live_open_ids=live)

    # La propiedad esencial: menos intentos que vueltas. Sin tope serian 40,
    # que es como se comporto en produccion (196 en 20 min).
    assert cancel.call_count < 40, (
        f"el bucle NO para: {cancel.call_count} intentos en 40 vueltas"
    )
    assert cancel.call_count == es.OCO_CANCEL_MAX_FAILURES, (
        f"esperados {es.OCO_CANCEL_MAX_FAILURES} intentos y luego abandono; "
        f"hubo {cancel.call_count}"
    )


def test_success_resets_the_counter():
    """Un exito limpia la cuenta: un fallo transitorio no debe gastar el cupo."""
    orphan, filled = _orphan(), _filled_sibling()
    svc, db = _service_with(orphan, filled)
    live = {str(orphan.exchange_order_id)}

    with patch.object(svc, "_find_oco_siblings", return_value=[filled]):
        with patch.object(svc, "_cancel_oco_sibling", side_effect=[False, False, True]):
            for _ in range(3):
                svc._sweep_orphaned_oco_siblings(db, live_open_ids=live)
        assert svc._oco_cancel_failures().get(str(orphan.exchange_order_id)) is None

        # Y tras el exito vuelve a tener el cupo entero disponible.
        with patch.object(svc, "_cancel_oco_sibling", return_value=False) as cancel2:
            for _ in range(40):
                svc._sweep_orphaned_oco_siblings(db, live_open_ids=live)
    assert cancel2.call_count == es.OCO_CANCEL_MAX_FAILURES


def test_other_orders_are_not_blocked():
    """Rendirse con una orden no puede dejar de intentar las demas."""
    stuck, other = _orphan("111"), _orphan("222")
    filled = _filled_sibling()
    svc = es.ExchangeSyncService.__new__(es.ExchangeSyncService)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [stuck, other]
    live = {"111", "222"}

    with patch.object(svc, "_find_oco_siblings", return_value=[filled]):
        with patch.object(svc, "_cancel_oco_sibling", return_value=False):
            for _ in range(40):
                svc._sweep_orphaned_oco_siblings(db, live_open_ids=live)

    fails = svc._oco_cancel_failures()
    # Las dos llegan al tope por separado; ninguna consume el cupo de la otra.
    assert fails["111"] > es.OCO_CANCEL_MAX_FAILURES
    assert fails["222"] > es.OCO_CANCEL_MAX_FAILURES
