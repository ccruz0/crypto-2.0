#!/usr/bin/env python3
"""
Self-check script for portfolio verification implementation.
Validates code structure and configuration without making external calls.

This script checks:
1. docker-compose.yml contains correct env var wiring
2. routes_dashboard.py contains proper auth guards
3. verify_portfolio_aws.sh uses correct headers and endpoints
4. Documentation matches implementation
"""

import sys
import os
import re
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent.parent
ERRORS = []
WARNINGS = []


def check_docker_compose():
    """Check docker-compose.yml for correct env var wiring."""
    compose_file = REPO_ROOT / "docker-compose.yml"
    
    if not compose_file.exists():
        ERRORS.append("docker-compose.yml not found")
        return
    
    content = compose_file.read_text()
    
    # Check for backend-aws service
    if "backend-aws:" not in content:
        ERRORS.append("backend-aws service not found in docker-compose.yml")
        return
    
    # Find backend-aws environment section
    backend_aws_start = content.find("backend-aws:")
    if backend_aws_start == -1:
        ERRORS.append("backend-aws service not found")
        return
    
    # Find environment section within backend-aws
    env_section_start = content.find("environment:", backend_aws_start)
    if env_section_start == -1:
        ERRORS.append("environment section not found in backend-aws")
        return
    
    # Find the end of backend-aws service
    # Look for next service that starts with 2 spaces and a letter (not comment or whitespace)
    remaining = content[env_section_start:]
    next_service_match = re.search(r'\n  [a-z]', remaining)
    if next_service_match:
        env_section_end = env_section_start + next_service_match.start()
    else:
        # Find next profile section or end of file
        next_profile = content.find("\n  # =", env_section_start)
        if next_profile == -1:
            env_section_end = len(content)
        else:
            env_section_end = next_profile
    
    env_section = content[env_section_start:env_section_end]
    
    # Check for ENABLE_DIAGNOSTICS_ENDPOINTS with default 0
    if "ENABLE_DIAGNOSTICS_ENDPOINTS" not in env_section:
        ERRORS.append("ENABLE_DIAGNOSTICS_ENDPOINTS not found in backend-aws environment")
    elif "${ENABLE_DIAGNOSTICS_ENDPOINTS:-0}" not in env_section:
        ERRORS.append("ENABLE_DIAGNOSTICS_ENDPOINTS must have default value 0")
    
    # Check for DIAGNOSTICS_API_KEY
    if "DIAGNOSTICS_API_KEY" not in env_section:
        ERRORS.append("DIAGNOSTICS_API_KEY not found in backend-aws environment")
    elif "${DIAGNOSTICS_API_KEY}" not in env_section:
        WARNINGS.append("DIAGNOSTICS_API_KEY should use ${DIAGNOSTICS_API_KEY} substitution")


def check_routes_dashboard():
    """Check routes_dashboard.py for proper auth guards."""
    routes_file = REPO_ROOT / "backend" / "app" / "api" / "routes_dashboard.py"
    
    if not routes_file.exists():
        ERRORS.append("routes_dashboard.py not found")
        return
    
    content = routes_file.read_text()
    
    # Check for _verify_diagnostics_auth function
    if "def _verify_diagnostics_auth" not in content:
        ERRORS.append("_verify_diagnostics_auth function not found")
        return
    
    # Check auth function checks both env vars
    auth_func_match = re.search(
        r"def _verify_diagnostics_auth.*?(?=\n\n|\ndef |\n@router)",
        content,
        re.DOTALL
    )
    if not auth_func_match:
        ERRORS.append("Could not parse _verify_diagnostics_auth function")
        return
    
    auth_func = auth_func_match.group(0)
    
    # Check for ENABLE_DIAGNOSTICS_ENDPOINTS check
    if 'os.getenv("ENABLE_DIAGNOSTICS_ENDPOINTS"' not in auth_func:
        ERRORS.append("_verify_diagnostics_auth must check ENABLE_DIAGNOSTICS_ENDPOINTS")
    
    # Check for DIAGNOSTICS_API_KEY check
    if 'os.getenv("DIAGNOSTICS_API_KEY")' not in auth_func:
        ERRORS.append("_verify_diagnostics_auth must check DIAGNOSTICS_API_KEY")
    
    # Check for header check
    if "X-Diagnostics-Key" not in auth_func and "x-diagnostics-key" not in auth_func:
        ERRORS.append("_verify_diagnostics_auth must check X-Diagnostics-Key header")
    
    # Check for 404 return (not 401)
    if 'status_code=404' not in auth_func:
        ERRORS.append("_verify_diagnostics_auth must return 404 (not 401)")
    
    # Check both endpoints call _verify_diagnostics_auth
    if content.count("_verify_diagnostics_auth(request)") < 2:
        ERRORS.append("Both portfolio-verify endpoints must call _verify_diagnostics_auth")
    
    # Check for portfolio-verify endpoint
    if '@router.get("/diagnostics/portfolio-verify"' not in content:
        ERRORS.append("/diagnostics/portfolio-verify endpoint not found")
    
    # Check for portfolio-verify-lite endpoint
    if '@router.get("/diagnostics/portfolio-verify-lite"' not in content:
        ERRORS.append("/diagnostics/portfolio-verify-lite endpoint not found")
    
    # Check lite endpoint doesn't return per-asset breakdown
    lite_match = re.search(
        r'@router\.get\("/diagnostics/portfolio-verify-lite".*?(?=\n\n@router|\ndef |\Z)',
        content,
        re.DOTALL
    )
    if lite_match:
        lite_func = lite_match.group(0)
        # Should not have diagnostic_data or per-asset logging
        if "diagnostic_data" in lite_func or "PORTFOLIO_DEBUG" in lite_func:
            # Check if it's only in comments or disabled
            if "No per-asset breakdown" not in lite_func:
                WARNINGS.append("portfolio-verify-lite should not include per-asset breakdown")


def check_verify_script():
    """Check verify_portfolio_aws.sh for correct usage."""
    script_file = REPO_ROOT / "verify_portfolio_aws.sh"
    
    if not script_file.exists():
        ERRORS.append("verify_portfolio_aws.sh not found")
        return
    
    content = script_file.read_text()
    
    # Check for X-Diagnostics-Key header
    if "X-Diagnostics-Key" not in content:
        ERRORS.append("verify_portfolio_aws.sh must use X-Diagnostics-Key header")
    
    # Check for lite endpoint
    if "portfolio-verify-lite" not in content:
        ERRORS.append("verify_portfolio_aws.sh must call portfolio-verify-lite endpoint")
    
    # Check for correct port (8002 for AWS backend)
    if "8002" not in content:
        WARNINGS.append("verify_portfolio_aws.sh should use port 8002 for AWS backend")
    
    # Check for PASS/FAIL output
    if "PASS" not in content or "FAIL" not in content:
        ERRORS.append("verify_portfolio_aws.sh must output PASS/FAIL")
    
    # Check for diff_usd output
    if "diff_usd" not in content and "DIFF_USD" not in content:
        ERRORS.append("verify_portfolio_aws.sh must output diff_usd")


def check_documentation():
    """Check documentation matches implementation."""
    runbook_file = REPO_ROOT / "PORTFOLIO_VERIFY_RUNBOOK.md"
    aws_setup_file = REPO_ROOT / "PORTFOLIO_VERIFY_AWS_SETUP.md"
    
    # Check runbook
    if runbook_file.exists():
        runbook_content = runbook_file.read_text()
        
        if "X-Diagnostics-Key" not in runbook_content:
            ERRORS.append("PORTFOLIO_VERIFY_RUNBOOK.md must mention X-Diagnostics-Key header")
        
        if "ENABLE_DIAGNOSTICS_ENDPOINTS" not in runbook_content:
            ERRORS.append("PORTFOLIO_VERIFY_RUNBOOK.md must mention ENABLE_DIAGNOSTICS_ENDPOINTS")
        
        if "default" not in runbook_content.lower() or "0" not in runbook_content:
            WARNINGS.append("PORTFOLIO_VERIFY_RUNBOOK.md should mention default disabled state")
    
    # Check AWS setup doc
    if aws_setup_file.exists():
        aws_content = aws_setup_file.read_text()
        
        if "ENABLE_DIAGNOSTICS_ENDPOINTS" not in aws_content:
            ERRORS.append("PORTFOLIO_VERIFY_AWS_SETUP.md must mention ENABLE_DIAGNOSTICS_ENDPOINTS")
        
        if "DIAGNOSTICS_API_KEY" not in aws_content:
            ERRORS.append("PORTFOLIO_VERIFY_AWS_SETUP.md must mention DIAGNOSTICS_API_KEY")


def main():
    """Run all checks."""
    print("🔍 Running self-check for portfolio verification implementation...")
    print("")
    
    check_docker_compose()
    check_routes_dashboard()
    check_verify_script()
    check_documentation()
    
    # Report results
    if ERRORS:
        print("❌ ERRORS FOUND:")
        for error in ERRORS:
            print(f"   - {error}")
        print("")
    
    if WARNINGS:
        print("⚠️  WARNINGS:")
        for warning in WARNINGS:
            print(f"   - {warning}")
        print("")
    
    if not ERRORS and not WARNINGS:
        print("✅ SELF-CHECK PASS: portfolio verification wiring is consistent")
        return 0
    elif not ERRORS:
        print("✅ SELF-CHECK PASS (with warnings): portfolio verification wiring is consistent")
        return 0
    else:
        print("❌ SELF-CHECK FAIL: portfolio verification wiring has errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())

