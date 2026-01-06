#!/usr/bin/env python3
"""
Telegram Safety Verification Script

Verifies that Telegram sending is properly configured and safe:
- LOCAL can send to real chat (with proper credentials)
- AWS cannot send to real chat (blocked by default, no LOCAL creds)

Run from backend directory:
    python scripts/verify_telegram_safety.py

Or from project root:
    python backend/scripts/verify_telegram_safety.py
"""
import os
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.environment import getRuntimeEnv
from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
from app.core.config import Settings

def check_env_var(name: str) -> bool:
    """Check if environment variable is set (non-empty)"""
    value = os.getenv(name, "").strip()
    return bool(value)

def get_kill_switch_status(env: str, db) -> tuple[bool, bool]:
    """
    Get kill switch status from database.
    Returns: (exists, enabled)
    """
    try:
        setting_key = f"tg_enabled_{env.lower()}"
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == setting_key
        ).first()
        
        if setting:
            enabled = setting.setting_value.lower() == "true"
            return (True, enabled)
        else:
            # Default: true for local, false for aws
            default_enabled = (env == "local")
            return (False, default_enabled)
    except Exception as e:
        print(f"  ⚠️  Error reading kill switch: {e}")
        return (False, False)

def determine_send_status(env: str, kill_switch_enabled: bool, has_token: bool, has_chat_id: bool, has_local_creds: bool) -> tuple[bool, str]:
    """
    Determine if sending is allowed and why.
    Returns: (allowed, reason)
    """
    if not kill_switch_enabled:
        return (False, "kill_switch_disabled")
    
    if env == "aws":
        if has_local_creds:
            return (False, "aws_has_local_credentials")
        if not has_token or not has_chat_id:
            return (False, "missing_aws_credentials")
        return (True, "allowed")
    else:  # local
        if not has_token or not has_chat_id:
            return (False, "missing_local_credentials")
        return (True, "allowed")

def main():
    """Run verification checks"""
    print("=" * 70)
    print("TELEGRAM SAFETY VERIFICATION")
    print("=" * 70)
    print()
    
    # Get runtime environment
    try:
        runtime_env = getRuntimeEnv()
        print(f"✓ Runtime Environment: {runtime_env.upper()}")
    except Exception as e:
        print(f"✗ Failed to get runtime environment: {e}")
        sys.exit(1)
    
    if runtime_env not in ["local", "aws"]:
        print(f"✗ Invalid environment: {runtime_env} (must be 'local' or 'aws')")
        sys.exit(1)
    
    print()
    print("1. ENVIRONMENT CHECK")
    print("-" * 70)
    env_var = os.getenv("ENVIRONMENT", "").strip().lower()
    if env_var == runtime_env:
        print(f"  ✓ ENVIRONMENT={env_var} (matches runtime)")
    else:
        print(f"  ✗ ENVIRONMENT={env_var} (does not match runtime {runtime_env})")
        sys.exit(1)
    
    print()
    print("2. TELEGRAM CREDENTIALS CHECK")
    print("-" * 70)
    
    # Check LOCAL credentials
    has_local_token = check_env_var("TELEGRAM_BOT_TOKEN_LOCAL")
    has_local_chat_id = check_env_var("TELEGRAM_CHAT_ID_LOCAL")
    has_generic_token = check_env_var("TELEGRAM_BOT_TOKEN")
    has_generic_chat_id = check_env_var("TELEGRAM_CHAT_ID")
    
    # Check AWS credentials
    has_aws_token = check_env_var("TELEGRAM_BOT_TOKEN_AWS")
    has_aws_chat_id = check_env_var("TELEGRAM_CHAT_ID_AWS")
    
    print(f"  TELEGRAM_BOT_TOKEN_LOCAL: {'✓ PRESENT' if has_local_token else '✗ MISSING'}")
    print(f"  TELEGRAM_CHAT_ID_LOCAL: {'✓ PRESENT' if has_local_chat_id else '✗ MISSING'}")
    print(f"  TELEGRAM_BOT_TOKEN_AWS: {'✓ PRESENT' if has_aws_token else '✗ MISSING'}")
    print(f"  TELEGRAM_CHAT_ID_AWS: {'✓ PRESENT' if has_aws_chat_id else '✗ MISSING'}")
    print(f"  TELEGRAM_BOT_TOKEN (generic): {'⚠️  PRESENT' if has_generic_token else '✓ NOT SET'}")
    print(f"  TELEGRAM_CHAT_ID (generic): {'⚠️  PRESENT' if has_generic_chat_id else '✓ NOT SET'}")
    
    # Environment-specific checks
    has_local_creds = has_local_token or has_local_chat_id
    has_generic_creds = has_generic_token or has_generic_chat_id
    
    if runtime_env == "local":
        if not has_local_token and not has_generic_token:
            print(f"  ✗ LOCAL: No bot token found (TELEGRAM_BOT_TOKEN_LOCAL or TELEGRAM_BOT_TOKEN)")
            sys.exit(1)
        if not has_local_chat_id and not has_generic_chat_id:
            print(f"  ✗ LOCAL: No chat ID found (TELEGRAM_CHAT_ID_LOCAL or TELEGRAM_CHAT_ID)")
            sys.exit(1)
        print(f"  ✓ LOCAL: Credentials present")
    else:  # aws
        if has_local_token or has_local_chat_id:
            print(f"  ✗ AWS: LOCAL credentials detected (should NOT be present)")
            sys.exit(1)
        if has_generic_token or has_generic_chat_id:
            print(f"  ✗ AWS: Generic credentials detected (should use *_AWS vars)")
            sys.exit(1)
        print(f"  ✓ AWS: No LOCAL credentials (safe)")
        if not has_aws_token or not has_aws_chat_id:
            print(f"  ⚠️  AWS: AWS credentials missing (sending will be blocked)")
    
    print()
    print("3. KILL SWITCH CHECK")
    print("-" * 70)
    
    db = SessionLocal()
    try:
        kill_switch_exists, kill_switch_enabled = get_kill_switch_status(runtime_env, db)
        setting_key = f"tg_enabled_{runtime_env}"
        
        if kill_switch_exists:
            print(f"  ✓ Kill switch {setting_key}: {'ENABLED' if kill_switch_enabled else 'DISABLED'}")
        else:
            default_status = "ENABLED" if runtime_env == "local" else "DISABLED"
            print(f"  ⚠️  Kill switch {setting_key}: NOT SET (defaults to {default_status})")
    finally:
        db.close()
    
    print()
    print("4. SEND STATUS")
    print("-" * 70)
    
    # Determine effective credentials for current env
    if runtime_env == "local":
        effective_token = has_local_token or has_generic_token
        effective_chat_id = has_local_chat_id or has_generic_chat_id
    else:  # aws
        effective_token = has_aws_token
        effective_chat_id = has_aws_chat_id
    
    allowed, reason = determine_send_status(
        runtime_env,
        kill_switch_enabled,
        effective_token,
        effective_chat_id,
        has_local_creds
    )
    
    if allowed:
        print(f"  ✓ SENDING ALLOWED")
        print(f"    Reason: {reason}")
    else:
        print(f"  ✗ SENDING BLOCKED")
        print(f"    Reason: {reason}")
    
    print()
    print("=" * 70)
    if allowed:
        print("RESULT: PASS - Telegram sending is ALLOWED")
        print("=" * 70)
        sys.exit(0)
    else:
        print("RESULT: FAIL - Telegram sending is BLOCKED")
        print("=" * 70)
        sys.exit(1)

if __name__ == "__main__":
    main()

