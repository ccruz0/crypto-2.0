import os
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import pytz
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.services.telegram_notifier import telegram_notifier
from app.services.brokers.crypto_com_trade import trade_client
from app.core.runtime import get_runtime_origin
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.database import SessionLocal
import json
from app.utils.http_client import http_get, http_post

logger = logging.getLogger(__name__)

# Bali timezone (UTC+8)
BALI_TZ = pytz.timezone('Asia/Makassar')  # Makassar is the same timezone as Bali (WITA)

# Friendly labels for decision reason codes in the daily rollup.
_REASON_CODE_LABELS = {
    "GUARDRAIL_BLOCKED": "Bloqueado por guardrail",
    "ONE_ACTIVE_TRADE_PER_COIN": "Máx. 1 trade activo por moneda (límite per-coin)",
    "SYSTEM_CORE_MAX_OPEN_TRADES": "Máx. trades abiertos (portfolio)",
    "SYSTEM_CORE_RSI": "RSI fuera de rango (system_core)",
    "SYSTEM_CORE_MA200": "Precio vs MA200 (system_core)",
    "SYSTEM_CORE_MAX_TRADE_USD": "Tope USD por trade (system_core)",
    "SYSTEM_CORE_DAILY_DRAWDOWN": "Drawdown diario (system_core)",
    "INVALID_TRADE_AMOUNT": "Amount USD no configurado",
    "TRADE_DISABLED": "Trade desactivado",
    "ALERTS_DISABLED": "Alertas desactivadas",
    "ALERT_DISABLED": "Alertas desactivadas",
    "COOLDOWN_ACTIVE": "Cooldown activo",
    "RECENT_ORDERS_COOLDOWN": "Cooldown de órdenes recientes",
    "ALREADY_HAS_OPEN_ORDER": "Ya hay orden abierta",
    "MAX_OPEN_TRADES_REACHED": "Máx. trades abiertos",
    "INSUFFICIENT_AVAILABLE_BALANCE": "Balance insuficiente",
    "INSUFFICIENT_FUNDS": "Fondos insuficientes",
    "MIN_NOTIONAL_NOT_MET": "Notional mínimo no cumplido",
    "EXCHANGE_REJECTED": "Rechazado por el exchange",
    "AUTHENTICATION_ERROR": "Error de autenticación",
    "EXCHANGE_ERROR_UNKNOWN": "Error del exchange",
    "RATE_LIMIT": "Rate limit",
    "TIMEOUT": "Timeout",
    "SAFETY_GUARD": "Safety guard",
    "ORDER_CREATION_LOCK": "Lock de creación de orden",
    "IDEMPOTENCY_BLOCKED": "Bloqueo de idempotencia",
    "TELEGRAM_API_ERROR": "Error de Telegram (API)",
    "THROTTLED_DUPLICATE_ALERT": "Alerta duplicada (throttle)",
}

# Alert-pipeline noise: every monitor cycle re-logs these while a signal is sticky.
# They are NOT honest "órdenes no ejecutadas" counts — exclude from the rollup.
_EXCLUDED_NOISE_REASON_CODES = frozenset(
    {
        "COOLDOWN_ACTIVE",
        "THROTTLED_DUPLICATE_ALERT",
        "RECENT_ORDERS_COOLDOWN",
    }
)

# Sticky expected blocks: collapse to one episode per (symbol, reason) with duration.
_STICKY_EPISODE_KEYS = frozenset(
    {
        "MAX_OPEN_TRADES_REACHED",
        "MAX_OPEN_ORDERS_TOTAL",
        "MAX_ORDERS_PER_SYMBOL",
        "TRADE_DISABLED",
        "ALERTS_DISABLED",
        "ALERT_DISABLED",
        "PORTFOLIO_VALUE_LIMIT",
        "MIN_SECONDS_BETWEEN_ORDERS",
    }
)

# Gap larger than this starts a new episode for the same symbol+reason.
_EPISODE_GAP = timedelta(minutes=30)

class DailySummaryService:
    """Daily summary service for portfolio and trading activity"""
    
    def __init__(self):
        self.telegram = telegram_notifier
        self.trade_client = trade_client
    
    def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary"""
        errors = []
        balance_data = {}
        open_orders = []
        recent_orders = []
        
        try:
            # Get account balance
            try:
                balance_response = self.trade_client.get_account_summary()
                if balance_response:
                    # Handle different response formats
                    if 'accounts' in balance_response:
                        # Convert accounts format to balance_data format
                        accounts = balance_response.get('accounts', [])
                        balance_data = {}
                        for acc in accounts:
                            currency = acc.get('currency', '')
                            balance_data[currency] = {
                                'available': acc.get('available', '0'),
                                'balance': acc.get('balance', '0')
                            }
                    elif 'data' in balance_response:
                        balance_data = balance_response.get('data', {})
                    elif 'result' in balance_response and 'data' in balance_response['result']:
                        balance_data = balance_response['result'].get('data', {})
                    else:
                        balance_data = balance_response
                else:
                    errors.append("get_account_summary returned None")
            except Exception as e:
                error_msg = f"Error getting account summary: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Get open orders
            try:
                open_orders_response = self.trade_client.get_open_orders()
                if open_orders_response:
                    open_orders = open_orders_response.get('data', [])
                else:
                    errors.append("get_open_orders returned None")
            except Exception as e:
                error_msg = f"Error getting open orders: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Get executed orders from last 24 hours
            try:
                executed_orders_response = self.trade_client.get_order_history(page_size=100)
                if executed_orders_response:
                    executed_orders = executed_orders_response.get('data', [])
                    
                    # Filter orders from last 24 hours
                    yesterday = datetime.now() - timedelta(days=1)
                    for order in executed_orders:
                        try:
                            # Handle both timestamp formats (seconds or milliseconds)
                            create_time = order.get('create_time', 0)
                            if create_time > 1e10:  # milliseconds
                                create_time = create_time / 1000
                            order_time = datetime.fromtimestamp(create_time)
                            if order_time >= yesterday:
                                recent_orders.append(order)
                        except (ValueError, TypeError, OSError) as e:
                            logger.warning(f"Error parsing order time: {e}, order: {order.get('order_id', 'unknown')}")
                            # Include order anyway if we can't parse time
                            recent_orders.append(order)
                else:
                    errors.append("get_order_history returned None")
            except Exception as e:
                error_msg = f"Error getting order history: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Return data even if some calls failed, but include errors
            result = {
                'balance': balance_data,
                'open_orders': open_orders,
                'recent_orders': recent_orders,
                'total_open_orders': len(open_orders),
                'total_executed_24h': len(recent_orders),
                'errors': errors
            }
            
            # Always return result, even if all calls failed
            # The send_daily_summary method will handle empty data gracefully
            if errors and not balance_data and not open_orders and not recent_orders:
                logger.warning(f"All portfolio summary calls failed: {errors}")
                # Still return the result structure so send_daily_summary can show a helpful message
                return result
            
            return result
            
        except Exception as e:
            error_msg = f"Unexpected error getting portfolio summary: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None
    
    def format_balance_summary(self, balance_data: Dict) -> str:
        """Format balance information"""
        if not balance_data:
            return "❌ No se pudo obtener el balance"
        
        summary = "💰 **Balance de Cuenta**\n"
        
        # Get USD/USDT balance
        usd_balance = 0
        crypto_balances = []
        
        # Handle different data structures
        if isinstance(balance_data, dict):
            for currency, data in balance_data.items():
                if isinstance(data, dict):
                    available = float(data.get('available', data.get('balance', 0)))
                elif isinstance(data, (int, float, str)):
                    available = float(data)
                else:
                    available = 0
                
                # Treat USD and USDT as the same
                if currency in ['USD', 'USDT']:
                    usd_balance += available
                elif available > 0:
                    crypto_balances.append(f"• {currency}: {available:.6f}")
        
        summary += f"💵 USD/USDT: ${usd_balance:,.2f}\n"
        
        if crypto_balances:
            summary += "\n📊 **Criptomonedas:**\n"
            summary += "\n".join(crypto_balances[:5])  # Show top 5
            if len(crypto_balances) > 5:
                summary += f"\n... y {len(crypto_balances) - 5} más"
        
        return summary
    
    def format_orders_summary(self, open_orders: List, recent_orders: List) -> str:
        """Format orders summary"""
        summary = f"📋 **Órdenes Activas:** {len(open_orders)}\n"
        
        if open_orders:
            summary += "\n🔄 **Órdenes Abiertas:**\n"
            for order in open_orders[:3]:  # Show first 3
                symbol = order.get('instrument_name', 'N/A')
                side = order.get('side', 'N/A')
                qty = float(order.get('quantity', 0))
                price = float(order.get('limit_price', 0))
                summary += f"• {symbol} {side} {qty:.6f} @ ${price:.4f}\n"
            
            if len(open_orders) > 3:
                summary += f"... y {len(open_orders) - 3} más\n"
        
        summary += f"\n📈 **Ejecutadas (24h):** {len(recent_orders)}\n"
        
        if recent_orders:
            summary += "\n✅ **Últimas Ejecuciones:**\n"
            for order in recent_orders[:3]:  # Show first 3
                symbol = order.get('instrument_name', 'N/A')
                side = order.get('side', 'N/A')
                qty = float(order.get('quantity', 0))
                price = float(order.get('avg_price', order.get('limit_price', 0)))
                status = order.get('status', 'N/A')
                summary += f"• {symbol} {side} {qty:.6f} @ ${price:.4f} ({status})\n"
            
            if len(recent_orders) > 3:
                summary += f"... y {len(recent_orders) - 3} más\n"
        
        return summary

    @staticmethod
    def _normalize_block_detail(text: Optional[str]) -> str:
        """Collapse volatile counters so (27/10) and (28/10) roll up together."""
        if not text:
            return ""
        # Never keep bot-token URLs in rollup keys / labels.
        cleaned = re.sub(
            r"https?://api\.telegram\.org/bot[^\s]+",
            "https://api.telegram.org/bot***/...",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***:***", cleaned)
        normalized = re.sub(r"\(\d+/\d+\)", "", cleaned)
        return " ".join(normalized.split()).strip()

    @staticmethod
    def _is_telegram_delivery_detail(detail: str) -> bool:
        upper = (detail or "").upper()
        return (
            "TELEGRAM API ERROR" in upper
            or "TELEGRAM HTTP" in upper
            or "API.TELEGRAM.ORG" in upper
            or "[TELEGRAM_FAILED]" in upper
        )

    @staticmethod
    def _is_alert_throttle_detail(detail: str) -> bool:
        """Pure alert throttle / duplicate gates — not order placement failures."""
        upper = (detail or "").upper()
        return any(
            token in upper
            for token in (
                "THROTTLED_TIME_GATE",
                "THROTTLED_PRICE_GATE",
                "THROTTLED_MIN_TIME",
                "THROTTLED_MIN_CHANGE",
                "THROTTLED_DUPLICATE",
                "ΔT=",
                "|ΔP|=",
            )
        )

    @classmethod
    def _non_executed_bucket_key(cls, row: Any) -> Tuple[str, str]:
        """Return (group_key, display_label) for a monitoring row."""
        reason_code = (getattr(row, "reason_code", None) or "").strip() or "UNKNOWN"
        detail = cls._normalize_block_detail(
            getattr(row, "throttle_reason", None) or getattr(row, "reason_message", None)
        )
        detail_upper = detail.upper()

        # Telegram delivery failures are never trading guardrails.
        if reason_code == "TELEGRAM_API_ERROR" or cls._is_telegram_delivery_detail(detail):
            http_match = re.search(r"\b(400|401|403|404|429|500)\b", detail)
            http_bit = f" HTTP {http_match.group(1)}" if http_match else ""
            return ("TELEGRAM_API_ERROR", f"Error de Telegram (API{http_bit})")

        if "MAX_OPEN_ORDERS_TOTAL" in detail_upper:
            return ("MAX_OPEN_ORDERS_TOTAL", "Tope global de órdenes abiertas")
        if "MAX_ORDERS_PER_SYMBOL" in detail_upper:
            return ("MAX_ORDERS_PER_SYMBOL", "Tope por símbolo / día")
        if "MAX_USD_PER_ORDER" in detail_upper:
            return ("MAX_USD_PER_ORDER", "Tope USD por orden")
        if "PORTFOLIO_VALUE_LIMIT" in detail_upper:
            return ("PORTFOLIO_VALUE_LIMIT", "Tope de valor de portfolio")
        if "AMOUNT USD" in detail_upper or "TRADE_AMOUNT" in detail_upper:
            return ("INVALID_TRADE_AMOUNT", "Amount USD no configurado")
        if "MIN_SECONDS_BETWEEN" in detail_upper:
            return ("MIN_SECONDS_BETWEEN_ORDERS", "Cooldown entre órdenes")
        if "ONE_ACTIVE_TRADE_PER_COIN" in detail_upper or "SYSTEM_CORE_ONE_ACTIVE" in detail_upper:
            return (
                "ONE_ACTIVE_TRADE_PER_COIN",
                "Máx. 1 trade activo por moneda (límite per-coin)",
            )

        label = _REASON_CODE_LABELS.get(reason_code, reason_code.replace("_", " ").title())
        if reason_code == "ONE_ACTIVE_TRADE_PER_COIN":
            return (
                "ONE_ACTIVE_TRADE_PER_COIN",
                "Máx. 1 trade activo por moneda (límite per-coin)",
            )
        if reason_code == "GUARDRAIL_BLOCKED" and detail:
            short = detail
            if short.lower().startswith("blocked:"):
                short = short[8:].strip()
            if len(short) > 60:
                short = short[:57] + "..."
            # Portfolio / named limits get a clean sticky key when present in short form.
            short_upper = short.upper()
            if "PORTFOLIO_VALUE_LIMIT" in short_upper:
                return ("PORTFOLIO_VALUE_LIMIT", "Tope de valor de portfolio")
            return (f"GUARDRAIL:{detail.lower()}", f"Guardrail: {short}")
        return (reason_code, label)

    @classmethod
    def _should_exclude_from_non_executed_rollup(cls, row: Any, key: str) -> bool:
        """Drop alert-throttle / cooldown re-logs that inflate the 24h summary."""
        reason_code = (getattr(row, "reason_code", None) or "").strip()
        if reason_code in _EXCLUDED_NOISE_REASON_CODES:
            return True
        if key in _EXCLUDED_NOISE_REASON_CODES:
            return True
        detail = cls._normalize_block_detail(
            getattr(row, "throttle_reason", None) or getattr(row, "reason_message", None)
        )
        if cls._is_alert_throttle_detail(detail) and reason_code != "TELEGRAM_API_ERROR":
            # Keep real order failures; drop pure alert gates.
            if reason_code in ("", "UNKNOWN", "THROTTLED_DUPLICATE_ALERT", "COOLDOWN_ACTIVE") or not reason_code:
                return True
            if reason_code in _EXCLUDED_NOISE_REASON_CODES:
                return True
        return False

    @staticmethod
    def _row_timestamp(row: Any) -> Optional[datetime]:
        ts = getattr(row, "timestamp", None)
        if ts is None:
            return None
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 90:
            return "<2m"
        minutes = int(round(seconds / 60.0))
        if minutes < 60:
            return f"~{minutes}m"
        hours = minutes / 60.0
        if hours < 10:
            return f"~{hours:.1f}h".replace(".0h", "h")
        return f"~{int(round(hours))}h"

    def get_non_executed_orders_summary(
        self,
        db: Optional[Session] = None,
        *,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """
        Roll up order attempts that did not execute in the last `hours`.

        Source: telegram_messages decision tracing / TRADE_BLOCKED / ORDER_FAILED /
        order_skipped rows written by the signal monitor lifecycle path.

        Aggregation:
        - Excludes alert cooldown / THROTTLED_* duplicate noise.
        - Sticky blocks (max open, portfolio limit, trade off, …) collapse to
          episodes per (symbol, reason) with first→last duration.
        - Real placement failures keep per-event counts.
        """
        from app.models.telegram_message import TelegramMessage

        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            rows = (
                db.query(TelegramMessage)
                .filter(
                    TelegramMessage.timestamp >= since,
                    or_(
                        TelegramMessage.decision_type.in_(("SKIPPED", "FAILED")),
                        TelegramMessage.order_skipped.is_(True),
                        TelegramMessage.throttle_status.in_(
                            ("TRADE_BLOCKED", "ORDER_FAILED")
                        ),
                    ),
                )
                .order_by(TelegramMessage.timestamp.asc())
                .limit(5000)
                .all()
            )

            # Chronological events after noise filter: (key, label, symbol, ts, dtype, sticky)
            events: List[Tuple[str, str, str, Optional[datetime], str, bool]] = []
            for row in rows:
                key, label = self._non_executed_bucket_key(row)
                if self._should_exclude_from_non_executed_rollup(row, key):
                    continue
                symbol = (getattr(row, "symbol", None) or "UNKNOWN").upper()
                ts = self._row_timestamp(row)
                dtype = getattr(row, "decision_type", None) or "SKIPPED"
                sticky = (
                    key in _STICKY_EPISODE_KEYS
                    or key.startswith("GUARDRAIL:")
                    or key == "TELEGRAM_API_ERROR"
                )
                events.append((key, label, symbol, ts, dtype, sticky))

            # Collapse sticky (symbol, reason) streams into episodes; keep raw counts for failures.
            open_eps: Dict[Tuple[str, str], Dict[str, Any]] = {}
            closed_eps: List[Dict[str, Any]] = []
            failure_buckets: Dict[str, Dict[str, Any]] = {}

            for key, label, symbol, ts, dtype, sticky in events:
                if not sticky:
                    bucket = failure_buckets.setdefault(
                        key,
                        {
                            "key": key,
                            "label": label,
                            "count": 0,
                            "episodes": 0,
                            "symbols": defaultdict(int),
                            "decision_types": defaultdict(int),
                            "symbol_details": [],
                            "mode": "events",
                        },
                    )
                    bucket["count"] += 1
                    bucket["episodes"] = bucket["count"]
                    bucket["symbols"][symbol] += 1
                    bucket["decision_types"][dtype] += 1
                    continue

                ep_id = (key, symbol)
                ep = open_eps.get(ep_id)
                if ep is None:
                    open_eps[ep_id] = {
                        "key": key,
                        "label": label,
                        "symbol": symbol,
                        "cycles": 1,
                        "first_ts": ts,
                        "last_ts": ts,
                        "decision_types": defaultdict(int, {dtype: 1}),
                    }
                    continue

                last_ts = ep["last_ts"]
                if ts is not None and last_ts is not None and (ts - last_ts) > _EPISODE_GAP:
                    closed_eps.append(ep)
                    open_eps[ep_id] = {
                        "key": key,
                        "label": label,
                        "symbol": symbol,
                        "cycles": 1,
                        "first_ts": ts,
                        "last_ts": ts,
                        "decision_types": defaultdict(int, {dtype: 1}),
                    }
                else:
                    ep["cycles"] += 1
                    ep["decision_types"][dtype] += 1
                    if ts is not None:
                        ep["last_ts"] = ts if ep["last_ts"] is None else max(ep["last_ts"], ts)
                        ep["first_ts"] = (
                            ts if ep["first_ts"] is None else min(ep["first_ts"], ts)
                        )

            closed_eps.extend(open_eps.values())

            buckets: Dict[str, Dict[str, Any]] = dict(failure_buckets)
            for ep in closed_eps:
                key = ep["key"]
                label = ep["label"]
                symbol = ep["symbol"]
                first_ts = ep.get("first_ts")
                last_ts = ep.get("last_ts")
                duration_s = 0.0
                if first_ts is not None and last_ts is not None:
                    duration_s = max(0.0, (last_ts - first_ts).total_seconds())
                bucket = buckets.setdefault(
                    key,
                    {
                        "key": key,
                        "label": label,
                        "count": 0,
                        "episodes": 0,
                        "symbols": defaultdict(int),
                        "decision_types": defaultdict(int),
                        "symbol_details": [],
                        "mode": "episodes",
                    },
                )
                bucket["mode"] = "episodes"
                bucket["episodes"] += 1
                bucket["count"] += 1
                bucket["symbols"][symbol] += 1
                for dt_key, dt_count in ep.get("decision_types", {}).items():
                    bucket["decision_types"][dt_key] += dt_count
                bucket["symbol_details"].append(
                    {
                        "symbol": symbol,
                        "cycles": ep.get("cycles", 1),
                        "duration_seconds": duration_s,
                        "duration_label": self._format_duration(duration_s)
                        if duration_s >= 60
                        else None,
                    }
                )

            ranked = sorted(
                buckets.values(),
                key=lambda b: (b.get("episodes") or b.get("count") or 0),
                reverse=True,
            )
            total = sum(int(b.get("episodes") or b.get("count") or 0) for b in ranked)
            symbols_affected = {
                sym for b in ranked for sym in b["symbols"].keys() if sym != "UNKNOWN"
            }

            return {
                "hours": hours,
                "total_events": total,
                "total_episodes": total,
                "unique_symbols": len(symbols_affected),
                "buckets": ranked,
            }
        except Exception as exc:
            logger.error("Failed to build non-executed orders summary: %s", exc, exc_info=True)
            return {
                "hours": hours,
                "total_events": 0,
                "total_episodes": 0,
                "unique_symbols": 0,
                "buckets": [],
                "error": str(exc),
            }
        finally:
            if owns_session and db is not None:
                db.close()

    def format_non_executed_orders_summary(self, rollup: Optional[Dict[str, Any]]) -> str:
        """Format non-executed order rollup for the daily Telegram message."""
        if not rollup:
            return ""

        hours = int(rollup.get("hours") or 24)
        total = int(rollup.get("total_episodes") or rollup.get("total_events") or 0)
        if rollup.get("error") and total == 0:
            return (
                f"🚫 **Órdenes no ejecutadas ({hours}h)**\n"
                f"⚠️ No se pudo generar el resumen: {str(rollup['error'])[:120]}\n"
            )

        if total == 0:
            return (
                f"🚫 **Órdenes no ejecutadas ({hours}h)**\n"
                "✅ Ningún bloqueo o fallo de orden relevante\n"
            )

        unique_symbols = int(rollup.get("unique_symbols") or 0)
        lines = [
            f"🚫 **Órdenes no ejecutadas ({hours}h):** {total} episodio(s)",
            f"📊 Símbolos afectados: {unique_symbols}",
            "",
        ]

        for bucket in (rollup.get("buckets") or [])[:8]:
            label = bucket["label"]
            mode = bucket.get("mode") or "events"
            details = bucket.get("symbol_details") or []
            if mode == "episodes" and details:
                # Prefer per-symbol duration lines for sticky blocks.
                details_sorted = sorted(
                    details,
                    key=lambda d: (d.get("duration_seconds") or 0, d.get("cycles") or 0),
                    reverse=True,
                )
                parts = []
                for d in details_sorted[:3]:
                    sym = d["symbol"]
                    dur = d.get("duration_label")
                    cycles = int(d.get("cycles") or 0)
                    if dur:
                        parts.append(f"{sym} {dur}")
                    elif cycles > 1:
                        parts.append(f"{sym}")
                    else:
                        parts.append(sym)
                extra = len(details_sorted) - len(parts)
                symbols_text = ", ".join(parts) if parts else "N/A"
                if extra > 0:
                    symbols_text += f" +{extra}"
                ep_count = int(bucket.get("episodes") or bucket.get("count") or 0)
                lines.append(f"• {label} — {ep_count} ep. ({symbols_text})")
            else:
                count = int(bucket.get("count") or 0)
                symbol_counts = sorted(
                    bucket["symbols"].items(), key=lambda item: item[1], reverse=True
                )
                top_symbols = [sym for sym, _ in symbol_counts[:3]]
                extra = len(symbol_counts) - len(top_symbols)
                symbols_text = ", ".join(top_symbols) if top_symbols else "N/A"
                if extra > 0:
                    symbols_text += f" +{extra}"
                lines.append(f"• {label} — {count}× ({symbols_text})")

        remaining = len(rollup.get("buckets") or []) - 8
        if remaining > 0:
            lines.append(f"... y {remaining} motivo(s) más")

        lines.append("")
        return "\n".join(lines)
    
    def send_daily_summary(self):
        """Send daily summary to Telegram"""
        try:
            logger.info("Generating daily summary...")
            
            # Get portfolio data
            portfolio_data = self.get_portfolio_summary()
            
            # Check if there were errors but we still have some data
            errors = portfolio_data.get('errors', []) if portfolio_data else []
            non_executed = self.get_non_executed_orders_summary(hours=24)
            
            # Create summary message
            message = f"🌅 **Resumen Diario - {datetime.now().strftime('%d/%m/%Y')}**\n\n"
            
            # If we have no data at all, send a minimal summary with error info
            if portfolio_data is None:
                message += "⚠️ **No se pudo obtener datos del portfolio**\n\n"
                message += "Posibles causas:\n"
                message += "• Problemas de conexión con el exchange\n"
                message += "• Error de autenticación\n"
                message += "• El servicio de trading no está disponible\n\n"
                message += self.format_non_executed_orders_summary(non_executed)
                message += f"\n⏰ Generado: {datetime.now().strftime('%H:%M:%S')}\n"
                message += "🤖 Trading Bot Automático"
                
                logger.warning("Daily summary: No portfolio data available, sending minimal summary")
                success = self.telegram.send_message(message, origin=get_runtime_origin())
                if success:
                    logger.info("Daily summary (minimal) sent successfully")
                else:
                    logger.error("Failed to send daily summary")
                return
            
            # Add balance summary (handle empty balance gracefully)
            balance = portfolio_data.get('balance', {})
            if balance:
                message += self.format_balance_summary(balance)
            else:
                message += "💰 **Balance de Cuenta**\n"
                message += "❌ No se pudo obtener el balance\n"
            message += "\n"
            
            # Add orders summary
            open_orders = portfolio_data.get('open_orders', [])
            recent_orders = portfolio_data.get('recent_orders', [])
            
            if open_orders or recent_orders:
                message += self.format_orders_summary(open_orders, recent_orders)
            else:
                message += "📋 **Órdenes**\n"
                message += "ℹ️ No hay órdenes activas o recientes para mostrar\n"

            message += "\n"
            message += self.format_non_executed_orders_summary(non_executed)
            
            # Add footer
            message += f"\n⏰ Generado: {datetime.now().strftime('%H:%M:%S')}"
            message += "\n🤖 Trading Bot Automático"
            
            # Add error warnings if any
            if errors:
                message += f"\n\n⚠️ Advertencias: {len(errors)} error(es) durante la obtención de datos"
                for error in errors[:3]:  # Show first 3 errors
                    # Truncate long errors but preserve error codes and important diagnostic info
                    error_clean = error.replace('\n', ' ')
                    
                    # For authentication errors (40101, 40103), show more context
                    if '40101' in error_clean or '40103' in error_clean or 'authentication' in error_clean.lower():
                        # Show up to 250 chars for auth errors to include full diagnostic message
                        if len(error_clean) > 250:
                            error_clean = error_clean[:247] + "..."
                    # If error contains a code, preserve at least 200 chars to show full code and context
                    elif 'code:' in error_clean.lower() or 'code ' in error_clean.lower():
                        if len(error_clean) > 200:
                            error_clean = error_clean[:197] + "..."
                    else:
                        if len(error_clean) > 120:
                            error_clean = error_clean[:117] + "..."
                    message += f"\n  • {error_clean}"
            
            # Send message
            success = self.telegram.send_message(message, origin=get_runtime_origin())
            
            if success:
                logger.info("Daily summary sent successfully")
            else:
                logger.error("Failed to send daily summary")
                
        except Exception as e:
            error_msg = f"Error sending daily summary: {e}"
            logger.error(error_msg, exc_info=True)
            try:
                # Preserve error codes in error messages
                error_str = str(e)
                if 'code:' in error_str.lower() or 'code ' in error_str.lower():
                    error_display = error_str[:250]  # Show more for errors with codes
                else:
                    error_display = error_str[:200]
                self.telegram.send_message(f"❌ Error en resumen diario: {error_display}", origin=get_runtime_origin())
            except Exception as e2:
                logger.error(f"Failed to send error message: {e2}", exc_info=True)

    def send_sell_orders_report(self, db: Session = None):
        """
        Send a report of all executed SELL orders from the last 24 hours
        with profit/loss per order and total P&L
        """
        try:
            # Use provided session or create new one
            if db is None:
                db = SessionLocal()
                should_close = True
            else:
                should_close = False
            
            try:
                # Calculate time range (last 24 hours) - use UTC for database queries
                now_utc = datetime.now(timezone.utc)
                yesterday_utc = now_utc - timedelta(hours=24)
                
                # Get Bali time for display
                now_bali = now_utc.astimezone(BALI_TZ)
                
                # Query executed SELL orders from last 24 hours
                sell_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.side == OrderSideEnum.SELL,
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ExchangeOrder.exchange_update_time >= yesterday_utc
                ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
                
                logger.info(f"Found {len(sell_orders)} executed SELL orders in last 24 hours")
                
                if not sell_orders:
                    message = f"📊 **Reporte de Ventas - {now_bali.strftime('%d/%m/%Y %H:%M')} (Bali)**\n\n"
                    message += "ℹ️ No se ejecutaron órdenes de venta en las últimas 24 horas."
                    self.telegram.send_message(message, origin=get_runtime_origin())
                    return
                
                # Build report message
                message = f"📊 **Reporte de Ventas - {now_bali.strftime('%d/%m/%Y %H:%M')} (Bali)**\n\n"
                message += f"⏰ Período: Últimas 24 horas\n"
                message += f"📈 Total de órdenes: {len(sell_orders)}\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                total_profit_loss = 0.0
                total_profit_loss_pct = 0.0
                orders_with_pnl = 0
                
                # Process each order
                for order in sell_orders:
                    symbol = order.symbol
                    sell_price = float(order.avg_price) if order.avg_price else float(order.price) if order.price else 0.0
                    quantity = float(order.quantity) if order.quantity else 0.0
                    order_id = order.exchange_order_id
                    order_time = order.exchange_update_time.strftime('%d/%m/%Y %H:%M:%S') if order.exchange_update_time else 'N/A'
                    order_role = order.order_role or 'SELL'
                    
                    # Try to find entry price from parent order or related BUY order
                    entry_price = None
                    if order.parent_order_id:
                        # Try to find parent BUY order
                        parent_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == order.parent_order_id
                        ).first()
                        if parent_order and parent_order.side == OrderSideEnum.BUY:
                            entry_price = float(parent_order.avg_price) if parent_order.avg_price else float(parent_order.price) if parent_order.price else None
                    
                    # If no parent order, try to find the most recent BUY order for this symbol before this SELL
                    if entry_price is None:
                        buy_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.side == OrderSideEnum.BUY,
                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                            ExchangeOrder.exchange_update_time < order.exchange_update_time
                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                        
                        if buy_order:
                            entry_price = float(buy_order.avg_price) if buy_order.avg_price else float(buy_order.price) if buy_order.price else None
                    
                    # Calculate P&L if entry price is available
                    pnl_info = ""
                    if entry_price and entry_price > 0:
                        profit_loss = (sell_price - entry_price) * quantity
                        profit_loss_pct = ((sell_price - entry_price) / entry_price) * 100
                        total_profit_loss += profit_loss
                        total_profit_loss_pct += profit_loss_pct
                        orders_with_pnl += 1
                        
                        pnl_emoji = "💰" if profit_loss >= 0 else "💸"
                        pnl_sign = "+" if profit_loss >= 0 else ""
                        pnl_info = f"\n   {pnl_emoji} P&L: {pnl_sign}${profit_loss:,.2f} ({pnl_sign}{profit_loss_pct:,.2f}%)"
                        pnl_info += f"\n   💵 Entrada: ${entry_price:,.4f}"
                    
                    # Format order line. Distinguish a direct exit (market/limit
                    # sell placed by the bot) from a protective SL/TP order so the
                    # operator can tell at a glance it was not a stop-loss/take-profit.
                    order_type_str = str(order.order_type or "").upper()
                    if order_role == "TAKE_PROFIT":
                        role_emoji, role_text = "🚀", "TP"
                    elif order_role == "STOP_LOSS":
                        role_emoji, role_text = "🛑", "SL"
                    elif "LIMIT" in order_type_str:
                        role_emoji, role_text = "🔴", "Venta (Límite)"
                    else:
                        role_emoji, role_text = "🔴", "Venta de Mercado"
                    
                    message += f"• <b>{symbol}</b> {role_emoji} {role_text}\n"
                    message += f"   💵 Precio: ${sell_price:,.4f}\n"
                    message += f"   📦 Cantidad: {quantity:,.6f}\n"
                    message += f"   💰 Total: ${(sell_price * quantity):,.2f}\n"
                    if pnl_info:
                        message += pnl_info
                    message += f"\n   🆔 ID: {order_id}\n"
                    message += f"   ⏰ {order_time}\n\n"
                
                # Add summary
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                message += f"📊 <b>RESUMEN</b>\n"
                message += f"   Total órdenes: {len(sell_orders)}\n"
                
                if orders_with_pnl > 0:
                    avg_pnl_pct = total_profit_loss_pct / orders_with_pnl
                    total_emoji = "💰" if total_profit_loss >= 0 else "💸"
                    total_sign = "+" if total_profit_loss >= 0 else ""
                    message += f"   {total_emoji} P&L Total: {total_sign}${total_profit_loss:,.2f}\n"
                    message += f"   📈 P&L Promedio: {total_sign}{avg_pnl_pct:,.2f}%\n"
                    message += f"   ✅ Órdenes con P&L: {orders_with_pnl}/{len(sell_orders)}\n"
                else:
                    message += f"   ⚠️ No se pudo calcular P&L (falta precio de entrada)\n"
                
                message += f"\n⏰ Generado: {now_bali.strftime('%H:%M:%S')} (Bali)\n"
                message += "🤖 Trading Bot Automático"
                
                # ============================================================
                # WORKING TELEGRAM PATH (CANONICAL) - Daily Sales Report
                # ============================================================
                # Trigger: Scheduled task (scheduler.py) → send_sell_orders_report()
                # Message Builder: Builds message with sales data
                # Telegram Sender: self.telegram.send_message(message)
                #   → telegram_notifier.send_message() [telegram_notifier.py:151]
                #   → Uses: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID env vars
                #   → Origin: Defaults to get_runtime_origin() → "AWS" in AWS
                #   → API Call: http_post("https://api.telegram.org/bot{token}/sendMessage", calling_module="daily_summary")
                #   → Result: Message sent to Telegram chat
                # ============================================================
                # ALL other alerts (signals, monitoring, watchlist, CPI) should
                # use the SAME path: telegram_notifier.send_message()
                # ============================================================
                success = self.telegram.send_message(message, origin=get_runtime_origin())
                
                if success:
                    logger.info(f"Sell orders report sent successfully: {len(sell_orders)} orders, P&L: ${total_profit_loss:,.2f}")
                else:
                    logger.error("Failed to send sell orders report")
                
                # Commit changes if we created the session (though this is read-only, commit for consistency)
                if should_close:
                    try:
                        db.commit()
                        logger.debug("DailySummaryService: Committed database changes")
                    except Exception as commit_err:
                        logger.error(f"DailySummaryService: Error committing changes: {commit_err}", exc_info=True)
                        db.rollback()
                    
            except Exception as inner_e:
                logger.error(f"Error in send_sell_orders_report inner block: {inner_e}", exc_info=True)
                if should_close and db:
                    try:
                        db.rollback()
                        logger.debug("DailySummaryService: Rolled back database changes due to inner error")
                    except Exception as rollback_err:
                        logger.error(f"DailySummaryService: Error rolling back: {rollback_err}", exc_info=True)
                raise
            finally:
                if should_close:
                    db.close()
                    
        except Exception as e:
            logger.error(f"Error sending sell orders report: {e}", exc_info=True)
            self.telegram.send_message(f"❌ Error en reporte de ventas: {str(e)}", origin=get_runtime_origin())

# Global instance
daily_summary_service = DailySummaryService()
