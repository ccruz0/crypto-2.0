"""Canonical Phase 4B remediation template catalog for ATP production failures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FixTemplate:
    """Deterministic fix template for investigation → proposal workflow."""

    fix_template_id: str
    description: str
    match_patterns: tuple[str, ...]
    target_files: tuple[str, ...]
    recommended_fix: str
    risk_level: str
    test_paths: tuple[str, ...]
    validation_rules: tuple[str, ...]
    supported_investigations: tuple[str, ...] = ()
    root_cause_exact: str | None = None
    strategy: str = "template"
    noop_reason: str = ""

    def to_dict(self, *, include_full: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "fix_template_id": self.fix_template_id,
            "description": self.description,
            "match_patterns": list(self.match_patterns),
            "target_files": list(self.target_files),
            "recommended_fix": self.recommended_fix,
            "risk_level": self.risk_level,
            "test_paths": list(self.test_paths),
            "validation_rules": list(self.validation_rules),
            "supported_investigations": list(self.supported_investigations),
            "strategy": self.strategy,
        }
        if include_full:
            payload["root_cause_exact"] = self.root_cause_exact
            payload["noop_reason"] = self.noop_reason
            # Backward compatibility for legacy consumers expecting ``match``.
            payload["match"] = self.root_cause_exact or (
                self.match_patterns[0] if self.match_patterns else ""
            )
        else:
            payload["match"] = self.root_cause_exact or (
                self.match_patterns[0] if self.match_patterns else ""
            )
        return payload

    def to_summary_dict(self) -> dict[str, Any]:
        """Public list view for GET /api/jarvis/templates."""
        return {
            "fix_template_id": self.fix_template_id,
            "description": self.description,
            "target_files": list(self.target_files),
            "supported_investigations": list(self.supported_investigations),
            "risk_level": self.risk_level,
        }


FIX_TEMPLATES: tuple[FixTemplate, ...] = (
    FixTemplate(
        fix_template_id="orders.trigger_50001_cache_independent",
        description="Trigger-order 50001 failure must not block regular open-order cache updates.",
        match_patterns=(
            "trigger order api failure blocks cache",
            "trigger.?order.*50001",
            "50001.*trigger",
            "trigger_orders_error_code.*50001",
            "cache update.*abort",
            "trigger.*sync.*fail",
        ),
        root_cause_exact="Trigger order API failure blocks cache updates",
        target_files=(
            "backend/app/services/exchange_sync.py",
            "backend/app/services/unified_open_orders_fetch.py",
            "backend/tests/test_crypto_com_sync_status.py",
        ),
        recommended_fix=(
            "Allow regular open orders to update cache independently when trigger-order sync fails."
        ),
        risk_level="medium",
        test_paths=("backend/tests/test_crypto_com_sync_status.py",),
        validation_rules=(
            "fetch_unified_open_orders handles trigger 50001 as non-fatal",
            "regular open orders still populate cache when trigger sync fails",
        ),
        supported_investigations=("orders", "dashboard", "open_orders_mismatch"),
        noop_reason=(
            "The trigger-order 50001 cache-independent fetch path is already implemented "
            "in the repository."
        ),
    ),
    FixTemplate(
        fix_template_id="crypto.auth_40101_mismatch",
        description="Crypto.com 40101 authentication failures from credential or runtime.env mismatch.",
        match_patterns=(
            "40101",
            "authentication fail",
            "auth failure",
            "key/secret mismatch",
            "secret copied multiple",
            "runtime.env credential",
            "duplicated api secret",
            "duplicat.*secret",
            "credential mismatch",
            "private endpoints fail",
            "secret length abnormal",
        ),
        root_cause_exact=(
            "Duplicated API secret in runtime.env causes Crypto.com auth failure (40101)"
        ),
        target_files=(
            "backend/app/utils/credential_resolver.py",
            "backend/scripts/diagnose_crypto_com_auth.py",
            "backend/app/core/crypto_com_guardrail.py",
        ),
        recommended_fix=(
            "Verify key/secret pair, deduplicate runtime.env entries, confirm allowlisted IP, "
            "and re-run auth diagnostics."
        ),
        risk_level="high",
        test_paths=(
            "backend/tests/test_crypto_com_sync_status.py",
            "backend/tests/test_render_runtime_env_exchange.py",
        ),
        validation_rules=(
            "single canonical EXCHANGE_CUSTOM_API_KEY/SECRET pair in runtime.env",
            "diagnose_crypto_com_auth reports consistent secret hash",
            "private API probe succeeds after credential cleanup",
        ),
        supported_investigations=("authentication", "credentials", "exchange_sync"),
        noop_reason="Credential resolver and 40101 diagnostics are already implemented.",
    ),
    FixTemplate(
        fix_template_id="dashboard.cache_db_mismatch",
        description="Dashboard open-order count differs from database while cache is empty or stale.",
        match_patterns=(
            "database has open orders but dashboard cache is empty",
            "dashboard count differs",
            "dashboard empty",
            "db contains rows",
            "cache=0.*db>0",
            "db.*\\d+.*cache.*0",
            "pending orders but.*cache is empty",
        ),
        root_cause_exact="Database has open orders but dashboard cache is empty",
        target_files=(
            "backend/app/services/open_orders_cache.py",
            "backend/app/api/routes_dashboard.py",
            "backend/app/api/routes_orders.py",
        ),
        recommended_fix=(
            "Use DB fallback for dashboard counts, refresh open_orders_cache, and preserve "
            "sync metadata during recovery."
        ),
        risk_level="medium",
        test_paths=("backend/tests/test_open_orders_db_fallback.py",),
        validation_rules=(
            "resolve_open_orders falls back to DB when cache empty",
            "dashboard routes expose source metadata",
        ),
        supported_investigations=("dashboard", "orders", "cache_mismatch"),
        noop_reason="Open orders DB fallback and cache refresh paths are already implemented.",
    ),
    FixTemplate(
        fix_template_id="portfolio.equity_derived_fallback",
        description="Portfolio equity falls back to derived balances when exchange equity is missing.",
        match_patterns=(
            "portfolio equity derived",
            "equity derived from balances",
            "exchange equity missing",
            "exchange equity null",
            "derived equity warning",
            "derived calculation active",
            "derived calculation",
            "missing equity field",
            "no equity field",
            "exchange-reported equity",
        ),
        root_cause_exact=(
            "Portfolio equity derived from balances because exchange API omits equity field"
        ),
        target_files=("backend/app/services/portfolio_cache.py",),
        recommended_fix=(
            "Detect absent exchange equity fields, improve reporting metadata, and preserve "
            "derived fallback only when exchange equity is unavailable."
        ),
        risk_level="low",
        test_paths=("backend/tests/test_portfolio_equity_field_discovery.py",),
        validation_rules=(
            "portfolio_cache prefers exchange-reported equity when present",
            "derived fallback metadata is exposed when exchange equity missing",
        ),
        supported_investigations=("portfolio", "equity", "wallet"),
        noop_reason="Portfolio cache equity detection and derived fallback metadata already exist.",
    ),
    FixTemplate(
        fix_template_id="websocket.same_origin_regression",
        description="Browser websocket URL regression causing mixed content or disconnects.",
        match_patterns=(
            "websocket price feed disconnected",
            "ws://api",
            "mixed content",
            "websocket disconnect",
            "browser websocket fail",
            "url generation mismatch",
            "same-origin",
            "window.location.host",
            "price stream ws",
        ),
        root_cause_exact="Websocket price feed disconnected or not receiving updates",
        target_files=(
            "frontend/src/lib/priceStreamWsUrl.ts",
            "frontend/scripts/verify_ws_prices_url.mjs",
        ),
        recommended_fix=(
            "Generate websocket URLs from window.location.host on same-origin deployments "
            "and add validation tests."
        ),
        risk_level="low",
        test_paths=("frontend/scripts/verify_ws_prices_url.mjs",),
        validation_rules=(
            "priceStreamWsUrl uses window.location.host in browser context",
            "internal docker hostnames are rejected in production browser context",
        ),
        supported_investigations=("websocket", "frontend", "prices"),
        noop_reason="Same-origin websocket URL generation is already implemented.",
    ),
    FixTemplate(
        fix_template_id="open_orders.stale_cache_fallback",
        description="In-memory open-order cache stale while exchange and DB still have orders.",
        match_patterns=(
            "stale cache",
            "empty in-memory cache",
            "exchange=1.*db=1.*cache=0",
            "stale_cache_db_fallback",
            "ok_db_fallback",
            "cache remains stale",
            "in-memory cache empty",
        ),
        target_files=(
            "backend/app/services/open_orders_resolver.py",
            "backend/app/api/routes_orders.py",
            "backend/app/api/routes_dashboard.py",
        ),
        recommended_fix=(
            "Resolve open orders via DB fallback with source metadata when cache is stale or empty."
        ),
        risk_level="medium",
        test_paths=("backend/tests/test_open_orders_db_fallback.py",),
        validation_rules=(
            "resolve_open_orders returns DB rows when cache empty",
            "resolver exposes stale_cache_db_fallback status",
        ),
        supported_investigations=("orders", "dashboard", "cache"),
        noop_reason="Stale-cache DB fallback resolver is already implemented.",
    ),
    FixTemplate(
        fix_template_id="exchange_sync_blocked_by_order_history",
        description="Long order-history scan delays or blocks open-order cache refresh.",
        match_patterns=(
            "sync_open_orders never",
            "order history scan",
            "sync_order_history monopol",
            "open order refresh delayed",
            "order history.*before.*sync_open_orders",
            "history window fetch",
            "blocks sync_open_orders",
        ),
        root_cause_exact="Order history sync monopolizes loop and delays open-order refresh",
        target_files=("backend/app/services/exchange_sync.py",),
        recommended_fix=(
            "Schedule independent open-order refresh, bound order-history scans, and add timeout "
            "handling so cache refresh is not blocked."
        ),
        risk_level="medium",
        test_paths=("backend/tests/test_crypto_com_sync_status.py",),
        validation_rules=(
            "open-order sync runs on an independent short-interval loop",
            "order-history scan runs separately and cannot block open-order refresh",
        ),
        supported_investigations=("orders", "exchange_sync", "scheduler"),
        noop_reason="Exchange sync runs open-order refresh on an independent loop before background order-history scans.",
    ),
    FixTemplate(
        fix_template_id="telegram.bot_command_setup_failure",
        description="Telegram setMyCommands or bot startup failures should not crash trading services.",
        match_patterns=(
            "setmycommands",
            "telegram bot startup",
            "bot initialization failure",
            "telegram api 400",
            "telegram startup warning",
            "setmycommands failure",
        ),
        root_cause_exact="Telegram bot command registration fails during startup",
        target_files=("backend/app/services/telegram_commands.py",),
        recommended_fix=(
            "Isolate Telegram command setup at startup, add retry handling, and degrade gracefully "
            "without blocking trading services."
        ),
        risk_level="low",
        test_paths=("backend/tests/test_telegram_secret_intake_e2e.py",),
        validation_rules=(
            "setMyCommands failures are logged and do not crash backend startup",
            "401/400 Telegram errors disable polling gracefully",
        ),
        supported_investigations=("telegram", "startup", "notifications"),
        noop_reason="Telegram startup isolation and graceful degradation are already implemented.",
    ),
)
