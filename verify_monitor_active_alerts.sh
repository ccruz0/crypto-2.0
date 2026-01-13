#!/bin/bash
# Verify Monitor Active Alerts fix: data verification + UI screenshots

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
DASHBOARD_URL="${DASHBOARD_URL:-https://dashboard.hilovivo.com}"

echo "🔍 Verifying Monitor Active Alerts Fix"
echo "======================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Step 1: Data verification
echo "📊 Step 1: Data Verification"
echo "---------------------------"
echo "Querying /api/monitoring/summary endpoint..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || { echo '❌ Cannot find project directory' && exit 1; }\",
        \"docker compose --profile aws exec -T backend-aws curl -s 'http://localhost:8000/api/monitoring/summary' > /tmp/monitoring_summary.json 2>&1 || curl -s 'http://localhost:8000/api/monitoring/summary' > /tmp/monitoring_summary.json 2>&1\",
        \"python3 - <<'PY'\",
        \"import json\",
        \"import sys\",
        \"try:\",
        \"  with open('/tmp/monitoring_summary.json', 'r') as f:\",
        \"    content = f.read()\",
        \"  if not content.strip():\",
        \"    print('❌ Empty response')\",
        \"    sys.exit(1)\",
        \"  d = json.loads(content)\",
        \"  print('✅ JSON parsed successfully')\",
        \"  print('')\",
        \"  print('📊 Counts:')\",
        \"  active_total = d.get('active_total') or d.get('active_alerts', 0)\",
        \"  sent_count = d.get('alert_counts', {}).get('sent', 0)\",
        \"  blocked_count = d.get('alert_counts', {}).get('blocked', 0)\",
        \"  failed_count = d.get('alert_counts', {}).get('failed', 0)\",
        \"  print(f'  active_total: {active_total}')\",
        \"  print(f'  sent_count: {sent_count}')\",
        \"  print(f'  blocked_count: {blocked_count}')\",
        \"  print(f'  failed_count: {failed_count}')\",
        \"  print('')\",
        \"  alerts = d.get('alerts', []) or []\",
        \"  print(f'📋 Rows: {len(alerts)}')\",
        \"  print('')\",
        \"  print('✅ Sample rows (first 3):')\",
        \"  for i, alert in enumerate(alerts[:3], 1):\",
        \"    print(f'  Row {i}:')\",
        \"    print(f'    type: {alert.get(\\\"type\\\", \\\"N/A\\\")}')\",
        \"    print(f'    symbol: {alert.get(\\\"symbol\\\", \\\"N/A\\\")}')\",
        \"    print(f'    status_label: {alert.get(\\\"status_label\\\", alert.get(\\\"alert_status\\\", \\\"N/A\\\"))}')\",
        \"    print(f'    reason_code: {alert.get(\\\"reason_code\\\", \\\"N/A\\\")}')\",
        \"    print(f'    reason_message: {alert.get(\\\"reason_message\\\", \\\"N/A\\\")[:50]}...' if alert.get('reason_message') else '    reason_message: N/A')\",
        \"    print('')\",
        \"  print('')\",
        \"  print('✅ Validation:')\",
        \"  if active_total == len(alerts):\",
        \"    print(f'  ✓ active_total ({active_total}) == len(rows) ({len(alerts)})')\",
        \"  else:\",
        \"    print(f'  ✗ active_total ({active_total}) != len(rows) ({len(alerts)})')\",
        \"  if active_total == sent_count + blocked_count + failed_count:\",
        \"    print(f'  ✓ active_total ({active_total}) == sent+blocked+failed ({sent_count + blocked_count + failed_count})')\",
        \"  else:\",
        \"    print(f'  ✗ active_total ({active_total}) != sent+blocked+failed ({sent_count + blocked_count + failed_count})')\",
        \"  all_have_status = all('status_label' in a or 'alert_status' in a for a in alerts)\",
        \"  if all_have_status:\",
        \"    print('  ✓ All rows have status_label or alert_status')\",
        \"  else:\",
        \"    print('  ✗ Some rows missing status_label/alert_status')\",
        \"  non_sent_have_reason = all(\",
        \"    (a.get('status_label', a.get('alert_status', '')) == 'SENT') or (a.get('reason_code') or a.get('reason_message'))\",
        \"    for a in alerts\",
        \"  )\",
        \"  if non_sent_have_reason:\",
        \"    print('  ✓ Non-SENT rows have reason_code/reason_message')\",
        \"  else:\",
        \"    print('  ✗ Some non-SENT rows missing reason_code/reason_message')\",
        \"except Exception as e:\",
        \"  print(f'❌ Error: {e}')\",
        \"  import traceback\",
        \"  traceback.print_exc()\",
        \"  sys.exit(1)\",
        \"PY\"
    ]" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "⏳ Waiting 30 seconds for execution..."
sleep 30

echo ""
echo "📊 Verification Result:"
echo "======================"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "📸 Step 2: UI Verification"
echo "-------------------------"
echo "Creating Playwright test for screenshots..."

# Create Playwright test
cat > /tmp/monitor_active_alerts.spec.ts << 'EOF'
import { test, expect } from '@playwright/test';

test.describe('Monitor Active Alerts Fix Verification', () => {
  test('should show Active Alerts with status labels from telegram_messages', async ({ page }) => {
    const baseURL = process.env.DASHBOARD_URL || 'http://localhost:3000';
    
    // Navigate to dashboard
    await page.goto(baseURL);
    
    // Wait for page to load
    await page.waitForLoadState('networkidle');
    
    // Take full page screenshot
    await page.screenshot({ path: 'monitor_page.png', fullPage: true });
    
    // Navigate to Monitoring tab (look for tab button or link)
    const monitoringTab = page.locator('text=Monitoring').or(page.locator('text=Monitor')).first();
    if (await monitoringTab.isVisible()) {
      await monitoringTab.click();
      await page.waitForTimeout(2000);
    } else {
      // Try direct navigation
      await page.goto(`${baseURL}?tab=monitoring`);
      await page.waitForTimeout(2000);
    }
    
    // Wait for Active Alerts panel
    const activeAlertsPanel = page.locator('text=Active Alerts').or(page.locator('h3:has-text("Active Alerts")')).first();
    await activeAlertsPanel.waitFor({ timeout: 10000 });
    
    // Take screenshot of Active Alerts panel
    const panel = page.locator('text=Active Alerts').locator('..').or(page.locator('h3:has-text("Active Alerts")').locator('..')).first();
    await panel.screenshot({ path: 'active_alerts_panel.png' });
    
    // Check for status labels (SENT, BLOCKED, FAILED) - not "signal detected"
    const statusLabels = page.locator('text=/SENT|BLOCKED|FAILED/i');
    const count = await statusLabels.count();
    
    // Take screenshot of table if it exists
    const table = page.locator('table').filter({ hasText: 'Active Alerts' }).or(page.locator('table').first());
    if (await table.isVisible()) {
      await table.screenshot({ path: 'active_alerts_table.png' });
    }
    
    // Assert that we have at least one status label (or table exists)
    expect(count).toBeGreaterThan(0);
    
    // Check for "signal detected" - should NOT be present
    const signalDetected = page.locator('text=/signal detected/i');
    const signalDetectedCount = await signalDetected.count();
    expect(signalDetectedCount).toBe(0);
  });
});
EOF

echo "✅ Playwright test created at /tmp/monitor_active_alerts.spec.ts"
echo ""
echo "💡 To run Playwright test:"
echo "   cd frontend"
echo "   npx playwright test /tmp/monitor_active_alerts.spec.ts --project=chromium"
echo ""
echo "📸 Screenshots will be saved in the frontend directory"
