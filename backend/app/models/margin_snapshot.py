"""Serie temporal del estado de margen de la cuenta.

Existe porque `portfolio_snapshots` guarda un solo numero —el valor total de
la cartera— y ese numero no dice cuanto margen queda antes de una
liquidacion. Con cross leverage la garantia es compartida: varias posiciones
que caen a la vez no producen una curva suave, producen una llamada de
margen. Medir eso exige historia, no una foto.

Los campos ya se leen del exchange en cada ciclo
(`crypto_com_trade.get_equity_from_user_balance`) y hasta ahora se usaban en
vivo y se descartaban. Esta tabla solo los persiste.

NO alimenta ninguna ruta de trading. Solo se escribe y se consulta.
"""
from sqlalchemy import Column, DateTime, Float, Index, Integer
from sqlalchemy.sql import func

from app.database import Base


class MarginSnapshot(Base):
    """Una fila por lectura del estado de margen."""

    __tablename__ = "margin_snapshots"

    id = Column(Integer, primary_key=True, index=True)

    # Patrimonio disponible como garantia.
    equity = Column(Float, nullable=True)
    # Margen ya comprometido por las posiciones abiertas.
    exposure = Column(Float, nullable=True)
    # Deuda viva agregada, tomada de portfolio_loans en el mismo instante que
    # el resto. Se guarda aqui aunque viva en otra tabla para que una sola
    # fila baste para reconstruir el estado sin cruzar por timestamp.
    borrowed_usd = Column(Float, nullable=True)

    # equity - exposure. Se persiste calculado en vez de derivarlo al leer:
    # si mañana cambia la formula, las filas viejas siguen contando lo que se
    # midio entonces y no lo que se calcularia hoy.
    free_margin = Column(Float, nullable=True)
    # exposure / equity. NULL cuando equity es 0 o falta: un ratio inventado
    # seria indistinguible de uno real, que es el error que ya se pago con
    # volume_ratio.
    margin_ratio = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_margin_snapshots_created", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<MarginSnapshot(equity={self.equity}, exposure={self.exposure}, "
            f"ratio={self.margin_ratio}, at={self.created_at})>"
        )
