#!/usr/bin/env python3
"""
Egress Audit Script: Verify all configured outbound URLs are allowlisted

This script validates that all outbound base URLs configured in the system
are in the egress allowlist and do not use raw IP addresses.
"""
import os
import sys
import re
from pathlib import Path
from typing import List, Tuple, Set
from urllib.parse import urlparse

# Add backend to path so we can import egress_guard
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from app.utils.egress_guard import (
    is_raw_ip,
    is_domain_allowed,
    ALLOWLISTED_DOMAINS,
    EgressGuardError,
    validate_outbound_url
)


def check_env_var(env_name: str, default_value: str = None) -> List[str]:
    """Check environment variable for URLs"""
    value = os.getenv(env_name, default_value or "")
    if not value:
        return []
    
    # Split by comma if multiple URLs
    urls = [url.strip() for url in value.split(",") if url.strip()]
    return urls


def check_docker_compose_env() -> List[Tuple[str, str]]:
    """Check docker-compose.yml for environment variables with URLs"""
    issues: List[Tuple[str, str]] = []
    
    compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
    if not compose_file.exists():
        return issues
    
    url_env_vars = [
        "VPN_GATE_URL",
        "EXCHANGE_CUSTOM_BASE_URL",
        "CRYPTO_REST_BASE",
        "CRYPTO_PROXY_URL",
        "TRADEBOT_BASE",
    ]
    
    with open(compose_file) as f:
        content = f.read()
        for env_var in url_env_vars:
            # Look for env_var in docker-compose.yml
            pattern = rf'{env_var}[=:]\s*([^\s\n]+)'
            matches = re.findall(pattern, content)
            for match in matches:
                # Clean up the match (remove quotes, etc.)
                url = match.strip().strip('"').strip("'")
                if url and not url.startswith("${"):
                    issues.append((env_var, url))
    
    return issues


def check_python_constants() -> List[Tuple[str, str]]:
    """Check Python constant files for URLs"""
    issues: List[Tuple[str, str]] = []
    
    backend_path = Path(__file__).parent.parent.parent / "backend"
    
    # Check crypto_com_constants.py
    constants_file = backend_path / "app" / "services" / "brokers" / "crypto_com_constants.py"
    if constants_file.exists():
        with open(constants_file) as f:
            content = f.read()
            # Look for REST_BASE
            pattern = r'REST_BASE\s*=\s*["\']([^"\']+)["\']'
            matches = re.findall(pattern, content)
            for match in matches:
                issues.append(("REST_BASE (crypto_com_constants.py)", match))
    
    return issues


def main():
    """Main audit function"""
    print("=" * 70)
    print("EGRESS AUDIT: Checking configured outbound URLs")
    print("=" * 70)
    print()
    
    all_issues: List[Tuple[str, str, str]] = []  # (source, url, issue)
    
    # Check environment variables
    print("1. Checking environment variables...")
    env_vars_to_check = {
        "VPN_GATE_URL": "https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT",
        "EXCHANGE_CUSTOM_BASE_URL": "",
        "CRYPTO_REST_BASE": "",
        "CRYPTO_PROXY_URL": "http://127.0.0.1:9000",  # Local proxy is OK
        "TRADEBOT_BASE": "",
    }
    
    for env_var, default in env_vars_to_check.items():
        value = os.getenv(env_var, default)
        if value:
            # Skip local proxy URLs (127.0.0.1, localhost, host.docker.internal)
            if any(local in value.lower() for local in ["127.0.0.1", "localhost", "host.docker.internal"]):
                print(f"   ✓ {env_var}: {value} (local/internal, OK)")
                continue
            
            try:
                parsed = urlparse(value)
                host = parsed.hostname
                if host:
                    if is_raw_ip(host):
                        all_issues.append((
                            f"Environment variable {env_var}",
                            value,
                            f"Raw IP address detected: {host}"
                        ))
                        print(f"   ✗ {env_var}: {value} (RAW IP - BLOCKED)")
                    elif not is_domain_allowed(host):
                        all_issues.append((
                            f"Environment variable {env_var}",
                            value,
                            f"Domain not in allowlist: {host}"
                        ))
                        print(f"   ✗ {env_var}: {value} (NOT ALLOWLISTED)")
                    else:
                        print(f"   ✓ {env_var}: {value} (allowlisted)")
            except Exception as e:
                all_issues.append((
                    f"Environment variable {env_var}",
                    value,
                    f"Error parsing URL: {e}"
                ))
                print(f"   ✗ {env_var}: {value} (ERROR: {e})")
        else:
            print(f"   - {env_var}: not set")
    
    print()
    
    # Check docker-compose.yml
    print("2. Checking docker-compose.yml...")
    compose_issues = check_docker_compose_env()
    for env_var, url in compose_issues:
        # Skip local proxy URLs
        if any(local in url.lower() for local in ["127.0.0.1", "localhost", "host.docker.internal"]):
            print(f"   ✓ {env_var}: {url} (local/internal, OK)")
            continue
        
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host:
                if is_raw_ip(host):
                    all_issues.append((
                        f"docker-compose.yml {env_var}",
                        url,
                        f"Raw IP address detected: {host}"
                    ))
                    print(f"   ✗ {env_var}: {url} (RAW IP - BLOCKED)")
                elif not is_domain_allowed(host):
                    all_issues.append((
                        f"docker-compose.yml {env_var}",
                        url,
                        f"Domain not in allowlist: {host}"
                    ))
                    print(f"   ✗ {env_var}: {url} (NOT ALLOWLISTED)")
                else:
                    print(f"   ✓ {env_var}: {url} (allowlisted)")
        except Exception as e:
            all_issues.append((
                f"docker-compose.yml {env_var}",
                url,
                f"Error parsing URL: {e}"
            ))
            print(f"   ✗ {env_var}: {url} (ERROR: {e})")
    
    if not compose_issues:
        print("   (no URL environment variables found in docker-compose.yml)")
    
    print()
    
    # Check Python constants
    print("3. Checking Python constant files...")
    const_issues = check_python_constants()
    for source, url in const_issues:
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host:
                if is_raw_ip(host):
                    all_issues.append((
                        source,
                        url,
                        f"Raw IP address detected: {host}"
                    ))
                    print(f"   ✗ {source}: {url} (RAW IP - BLOCKED)")
                elif not is_domain_allowed(host):
                    all_issues.append((
                        source,
                        url,
                        f"Domain not in allowlist: {host}"
                    ))
                    print(f"   ✗ {source}: {url} (NOT ALLOWLISTED)")
                else:
                    print(f"   ✓ {source}: {url} (allowlisted)")
        except Exception as e:
            all_issues.append((
                source,
                url,
                f"Error parsing URL: {e}"
            ))
            print(f"   ✗ {source}: {url} (ERROR: {e})")
    
    if not const_issues:
        print("   (no URL constants found)")
    
    print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    
    if all_issues:
        print(f"❌ Found {len(all_issues)} security issue(s):")
        print()
        for source, url, issue in all_issues:
            print(f"  • {source}")
            print(f"    URL: {url}")
            print(f"    Issue: {issue}")
            print()
        
        print("=" * 70)
        print("ACTION REQUIRED:")
        print("=" * 70)
        print("1. Remove or replace raw IP addresses with domain names")
        print("2. Add legitimate domains to ALLOWLISTED_DOMAINS in")
        print("   backend/app/utils/egress_guard.py")
        print("3. Verify all changes with: python scripts/security/egress_audit.py")
        print()
        sys.exit(1)
    else:
        print("✓ No security issues found!")
        print("  All configured outbound URLs are allowlisted and use domain names.")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()







