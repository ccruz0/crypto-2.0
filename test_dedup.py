#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.services.signal_order_orchestrator import create_order_intent
from app.api.routes_monitoring import update_telegram_message_decision_trace
from app.utils.decision_reason import make_skip, ReasonCode
import uuid

db = SessionLocal()
try:
    print('=== DEDUP TEST: Calling orchestrator with signal_id=144955 (should be DEDUP_SKIPPED) ===')
    order_intent, status = create_order_intent(
        db=db,
        signal_id=144955,
        symbol='SOL_USDT',
        side='BUY',
        message_content='[TEST] BUY SIGNAL: SOL_USDT @ $1.000000'
    )
    print(f'Orchestrator status: {status}')
    print(f'OrderIntent: {order_intent.id if order_intent else "None (dedup skipped)"}')
    
    if status == 'DEDUP_SKIPPED':
        print('✅ DEDUP_SKIPPED confirmed!')
        decision_reason = make_skip(
            reason_code=ReasonCode.IDEMPOTENCY_BLOCKED.value,
            message='Duplicate signal detected. Order was already attempted.',
            context={'symbol': 'SOL_USDT', 'signal_id': 144955},
            source='orchestrator'
        )
        update_telegram_message_decision_trace(
            db=db,
            symbol='SOL_USDT',
            message_pattern='BUY SIGNAL',
            decision_type='SKIPPED',
            reason_code=decision_reason.reason_code,
            reason_message=decision_reason.reason_message,
            context_json=decision_reason.context,
            correlation_id=str(uuid.uuid4())
        )
        print('✅ Decision trace updated')
    else:
        print(f'⚠️ Expected DEDUP_SKIPPED but got: {status}')
finally:
    db.close()
