#!/usr/bin/env python3
"""
Verify API credentials format - check for hidden characters, whitespace, etc.
"""

import os
import sys

api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY") or os.getenv("CRYPTO_API_KEY", "").strip()
api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET") or os.getenv("CRYPTO_API_SECRET", "").strip()

print("=" * 80)
print("CREDENTIAL VERIFICATION")
print("=" * 80)
print()

print(f"API Key:")
print(f"  Length: {len(api_key)} chars")
print(f"  Repr: {repr(api_key)}")
has_newline = '\n' in api_key
has_cr = '\r' in api_key
has_tab = '\t' in api_key
print(f"  Has newlines: {has_newline}")
print(f"  Has carriage returns: {has_cr}")
print(f"  Has tabs: {has_tab}")
print(f"  Leading/trailing whitespace: '{api_key[:5] if len(api_key) >= 5 else api_key}' ... '{api_key[-5:] if len(api_key) >= 5 else api_key}'")
print(f"  Stripped length: {len(api_key.strip())} chars")
print()

print(f"API Secret:")
print(f"  Length: {len(api_secret)} chars")
print(f"  Repr (first 20): {repr(api_secret[:20])}...")
print(f"  Repr (last 20): ...{repr(api_secret[-20:])}")
has_newline_sec = '\n' in api_secret
has_cr_sec = '\r' in api_secret
has_tab_sec = '\t' in api_secret
print(f"  Has newlines: {has_newline_sec}")
print(f"  Has carriage returns: {has_cr_sec}")
print(f"  Has tabs: {has_tab_sec}")
print(f"  Leading/trailing whitespace: '{api_secret[:5] if len(api_secret) >= 5 else api_secret}' ... '{api_secret[-5:] if len(api_secret) >= 5 else api_secret}'")
print(f"  Stripped length: {len(api_secret.strip())} chars")
print()

# Check expected lengths
if api_key.startswith("z3HWF8m292zJKABkzfXWvQ"):
    print("✅ API Key matches expected format")
else:
    print(f"⚠️  API Key does not match expected format")
    print(f"   Expected starts with: z3HWF8m292zJKABkzfXWvQ")
    print(f"   Actual starts with: {api_key[:22] if len(api_key) >= 22 else api_key}")

if api_secret.startswith("cxakp_"):
    print("✅ API Secret has expected prefix 'cxakp_'")
else:
    print(f"⚠️  API Secret does not have expected prefix")
    print(f"   Actual prefix: {api_secret[:6] if len(api_secret) >= 6 else api_secret}")

print()
print("=" * 80)

