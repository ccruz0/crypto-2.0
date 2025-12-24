#!/usr/bin/env python3
"""
Enable detailed authentication diagnostics
Sets CRYPTO_AUTH_DIAG=true to enable detailed logging
"""
import os
import sys
from pathlib import Path

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)
env_file = Path(project_root) / '.env.local'

print("=" * 80)
print("🔧 ENABLE AUTHENTICATION DIAGNOSTICS")
print("=" * 80)

if not env_file.exists():
    print(f"\n❌ .env.local not found at {env_file}")
    print("   Creating new .env.local file...")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.touch()

# Read existing content
lines = []
if env_file.exists():
    with open(env_file, 'r') as f:
        lines = f.readlines()

# Check if CRYPTO_AUTH_DIAG already exists
found = False
for i, line in enumerate(lines):
    if line.strip().startswith('CRYPTO_AUTH_DIAG'):
        lines[i] = 'CRYPTO_AUTH_DIAG=true\n'
        found = True
        print(f"\n✅ Updated existing CRYPTO_AUTH_DIAG setting")
        break

if not found:
    lines.append('\n# Enable detailed authentication diagnostics\n')
    lines.append('CRYPTO_AUTH_DIAG=true\n')
    print(f"\n✅ Added CRYPTO_AUTH_DIAG=true to .env.local")

# Write back
with open(env_file, 'w') as f:
    f.writelines(lines)

print(f"\n📝 Configuration updated in: {env_file}")
print(f"\n💡 To apply changes:")
print(f"   1. Restart backend: docker compose restart backend-aws")
print(f"   2. Run diagnostic: docker compose exec backend-aws python scripts/deep_auth_diagnostic.py")
print(f"\n⚠️  Note: This will log detailed authentication info (but not full secrets)")
print("=" * 80)

