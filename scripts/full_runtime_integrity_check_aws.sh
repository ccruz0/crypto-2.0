#!/usr/bin/env bash
set -euo pipefail

cd /Users/carloscruz/automated-trading-platform

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNED=0

echo -e "${BLUE}==============================${NC}"
echo -e "${BLUE} FULL RUNTIME INTEGRITY CHECK ${NC}"
echo -e "${BLUE}==============================${NC}"
echo

# Check 1: Backend health summary
echo -e "${BLUE}[1] Backend health summary${NC}"
echo "---------------------------"
if bash scripts/check_runtime_health_aws.sh 2>&1; then
    echo -e "${GREEN}✅ Backend health check PASSED${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${RED}❌ Backend health check FAILED${NC}"
    ((CHECKS_FAILED++))
fi
echo

# Check 2: SignalMonitor cycles
echo -e "${BLUE}[2] SignalMonitor cycles (last 50 lines)${NC}"
echo "----------------------------------------"
MONITOR_LOGS=$(bash scripts/aws_backend_logs.sh --tail 2000 2>&1 | grep -E "DEBUG_SIGNAL_MONITOR|SignalMonitorService|_run_signal_monitor" | tail -50 || true)
if [ -n "$MONITOR_LOGS" ]; then
    echo "$MONITOR_LOGS"
    CYCLE_COUNT=$(echo "$MONITOR_LOGS" | grep -c "cycle.*completed\|cycle.*started" || true)
    if [ "$CYCLE_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ SignalMonitor cycles detected ($CYCLE_COUNT cycles found)${NC}"
        ((CHECKS_PASSED++))
    else
        echo -e "${YELLOW}⚠️  SignalMonitor logs found but no cycle completion messages${NC}"
        ((CHECKS_WARNED++))
    fi
else
    echo -e "${RED}❌ No SignalMonitor logs found${NC}"
    ((CHECKS_FAILED++))
fi
echo

# Check 3: Strategy decisions
echo -e "${BLUE}[3] Strategy decisions (last 40 DEBUG_STRATEGY_FINAL)${NC}"
echo "------------------------------------------------------"
STRATEGY_LOGS=$(bash scripts/aws_backend_logs.sh --tail 2000 2>&1 | grep -E "DEBUG_STRATEGY_FINAL" | tail -40 || true)
if [ -n "$STRATEGY_LOGS" ]; then
    echo "$STRATEGY_LOGS"
    BUY_COUNT=$(echo "$STRATEGY_LOGS" | grep -c "decision=BUY" || true)
    SELL_COUNT=$(echo "$STRATEGY_LOGS" | grep -c "decision=SELL" || true)
    echo -e "${GREEN}✅ Strategy decisions found (BUY: $BUY_COUNT, SELL: $SELL_COUNT)${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${YELLOW}⚠️  No strategy debug logs found${NC}"
    ((CHECKS_WARNED++))
fi
echo

# Check 4: Alert emissions
echo -e "${BLUE}[4] Alert emissions (ALERT_EMIT_FINAL / send_*_signal)${NC}"
echo "-------------------------------------------------------"
ALERT_LOGS=$(bash scripts/aws_backend_logs.sh --tail 2000 2>&1 | grep -E "ALERT_EMIT_FINAL|send_buy_signal|send_sell_signal" | tail -40 || true)
if [ -n "$ALERT_LOGS" ]; then
    echo "$ALERT_LOGS"
    SUCCESS_COUNT=$(echo "$ALERT_LOGS" | grep -c "status=success" || true)
    if [ "$SUCCESS_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ Alert emissions found ($SUCCESS_COUNT successful alerts)${NC}"
        ((CHECKS_PASSED++))
    else
        echo -e "${YELLOW}⚠️  Alert logs found but no successful emissions${NC}"
        ((CHECKS_WARNED++))
    fi
else
    echo -e "${YELLOW}⚠️  No alert emission logs found (may be normal if no BUY/SELL signals)${NC}"
    ((CHECKS_WARNED++))
fi
echo

# Check 5: Throttled alerts
echo -e "${BLUE}[5] Throttled alerts (ALERT_THROTTLED)${NC}"
echo "---------------------------------------"
THROTTLE_LOGS=$(bash scripts/aws_backend_logs.sh --tail 2000 2>&1 | grep -E "ALERT_THROTTLED" | tail -40 || true)
if [ -n "$THROTTLE_LOGS" ]; then
    echo "$THROTTLE_LOGS"
    THROTTLE_COUNT=$(echo "$THROTTLE_LOGS" | wc -l | tr -d ' ')
    echo -e "${YELLOW}⚠️  Throttled alerts found ($THROTTLE_COUNT) - review throttle rules if unexpected${NC}"
    ((CHECKS_WARNED++))
else
    echo -e "${GREEN}✅ No throttled alerts found (normal if no alerts were throttled)${NC}"
    ((CHECKS_PASSED++))
fi
echo

# Check 6: Recent errors
echo -e "${BLUE}[6] Recent errors / exceptions${NC}"
echo "-----------------------------"
ERROR_LOGS=$(bash scripts/aws_backend_logs.sh --tail 5000 2>&1 | grep -E "Traceback|Exception|ERROR" | tail -40 || true)
if [ -n "$ERROR_LOGS" ]; then
    echo "$ERROR_LOGS"
    ERROR_COUNT=$(echo "$ERROR_LOGS" | wc -l | tr -d ' ')
    echo -e "${RED}❌ Recent errors/exceptions found ($ERROR_COUNT lines) - investigate immediately${NC}"
    ((CHECKS_FAILED++))
else
    echo -e "${GREEN}✅ No recent errors/exceptions found${NC}"
    ((CHECKS_PASSED++))
fi
echo

# Check 7: Docker container status
echo -e "${BLUE}[7] Docker container status (AWS)${NC}"
echo "----------------------------------"
if CONTAINER_STATUS=$(ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && docker ps --format '{{.Names}} {{.Status}}'" 2>&1); then
    echo "$CONTAINER_STATUS"
    BACKEND_STATUS=$(echo "$CONTAINER_STATUS" | grep "automated-trading-platform-backend" || true)
    if [ -z "$BACKEND_STATUS" ]; then
        echo -e "${RED}❌ Backend container not found${NC}"
        ((CHECKS_FAILED++))
    elif echo "$BACKEND_STATUS" | grep -q "healthy"; then
        echo -e "${GREEN}✅ Backend container is healthy${NC}"
        ((CHECKS_PASSED++))
    elif echo "$BACKEND_STATUS" | grep -q "unhealthy"; then
        echo -e "${RED}❌ Backend container is UNHEALTHY${NC}"
        ((CHECKS_FAILED++))
    else
        echo -e "${YELLOW}⚠️  Backend container status unclear: $BACKEND_STATUS${NC}"
        ((CHECKS_WARNED++))
    fi
else
    echo -e "${RED}❌ Failed to fetch docker status from AWS${NC}"
    ((CHECKS_FAILED++))
fi
echo

# Check 8: Crypto.com auth/proxy
echo -e "${BLUE}[8] Crypto.com auth / proxy status (last 400 log lines)${NC}"
echo "--------------------------------------------------------"
CRYPTO_LOGS=$(bash scripts/aws_backend_logs.sh --tail 400 2>&1 | grep -E "CRYPTO_AUTH_DIAG|Proxy authentication error|API credentials not configured" || true)
if [ -n "$CRYPTO_LOGS" ]; then
    echo "$CRYPTO_LOGS"
    if echo "$CRYPTO_LOGS" | grep -q "API credentials not configured"; then
        echo -e "${RED}❌ API credentials not configured - investigate credentials${NC}"
        ((CHECKS_FAILED++))
    elif echo "$CRYPTO_LOGS" | grep -q "Proxy authentication error"; then
        echo -e "${YELLOW}⚠️  Proxy authentication errors detected - check VPN/proxy${NC}"
        ((CHECKS_WARNED++))
    else
        echo -e "${GREEN}✅ Crypto.com auth logs found (review above for details)${NC}"
        ((CHECKS_PASSED++))
    fi
else
    echo -e "${GREEN}✅ No recent Crypto.com auth issues found${NC}"
    ((CHECKS_PASSED++))
fi
echo

# Check 9: Telegram status
echo -e "${BLUE}[9] Telegram status (including 409 conflicts)${NC}"
echo "----------------------------------------------"
TELEGRAM_LOGS=$(bash scripts/aws_backend_logs.sh --tail 400 2>&1 | grep -iE "telegram|409" | tail -40 || true)
if [ -n "$TELEGRAM_LOGS" ]; then
    echo "$TELEGRAM_LOGS"
    CONFLICT_COUNT=$(echo "$TELEGRAM_LOGS" | grep -c "409\|conflict" || true)
    if [ "$CONFLICT_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Telegram 409 conflicts detected ($CONFLICT_COUNT) - ensure only AWS backend uses bot token${NC}"
        ((CHECKS_WARNED++))
    else
        echo -e "${GREEN}✅ Telegram logs found (no conflicts)${NC}"
        ((CHECKS_PASSED++))
    fi
else
    echo -e "${GREEN}✅ No recent Telegram logs found${NC}"
    ((CHECKS_PASSED++))
fi
echo

# Final summary
echo -e "${BLUE}========== CHECK COMPLETE ==========${NC}"
echo
echo -e "Summary:"
echo -e "  ${GREEN}✅ Passed: $CHECKS_PASSED${NC}"
echo -e "  ${YELLOW}⚠️  Warnings: $CHECKS_WARNED${NC}"
echo -e "  ${RED}❌ Failed: $CHECKS_FAILED${NC}"
echo
echo "Expected healthy state:"
echo -e "  ${GREEN}✅ Backend health summary OK${NC}"
echo -e "  ${GREEN}✅ SignalMonitor cycles every ~30 seconds${NC}"
echo -e "  ${GREEN}✅ Strategy decisions present${NC}"
echo -e "  ${GREEN}✅ ALERT_EMIT_FINAL when BUY/SELL decisions exist${NC}"
echo -e "  ${GREEN}✅ No critical errors${NC}"
echo -e "  ${GREEN}✅ Containers healthy${NC}"
echo -e "  ${GREEN}✅ Crypto.com responding correctly${NC}"
echo -e "  ${GREEN}✅ Telegram not blocking outgoing alerts${NC}"
echo

if [ "$CHECKS_FAILED" -gt 0 ]; then
    echo -e "${RED}❌ INTEGRITY CHECK FAILED - Investigate failed checks above${NC}"
    exit 1
elif [ "$CHECKS_WARNED" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  INTEGRITY CHECK PASSED WITH WARNINGS - Review warnings above${NC}"
    exit 0
else
    echo -e "${GREEN}✅ INTEGRITY CHECK PASSED - All systems operational${NC}"
    exit 0
fi
