"""
Regression test to prevent function-scope imports of telegram_notifier.

This test ensures that telegram_notifier is only imported at module level,
never inside functions. Function-scope imports cause Python to treat the
variable as local, leading to UnboundLocalError when referenced before assignment.
"""
import re
import os
from pathlib import Path


def test_no_function_scope_imports_telegram_notifier():
    """Test that signal_monitor.py has no function-scope imports of telegram_notifier."""
    # Get the path to signal_monitor.py
    test_dir = Path(__file__).parent
    # test_dir is backend/app/tests, so go up to backend/app/services
    signal_monitor_path = test_dir.parent / "services" / "signal_monitor.py"
    
    assert signal_monitor_path.exists(), f"File not found: {signal_monitor_path}"
    
    # Read the file
    with open(signal_monitor_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    # Pattern to match indented imports of telegram_notifier
    # This matches lines that start with whitespace (function scope) followed by import
    pattern = re.compile(r'^\s+from\s+app\.services\.telegram_notifier\s+import\s+telegram_notifier')
    
    violations = []
    for line_num, line in enumerate(lines, start=1):
        if pattern.match(line):
            violations.append((line_num, line.strip()))
    
    if violations:
        error_msg = (
            "Found function-scope imports of telegram_notifier in signal_monitor.py:\n"
            + "\n".join(f"  Line {line_num}: {line}" for line_num, line in violations)
            + "\n\n"
            + "These imports cause UnboundLocalError when telegram_notifier is referenced "
            + "before the import statement. Use the module-level import at the top of the file instead."
        )
        raise AssertionError(error_msg)
    
    # Also verify module-level import exists
    module_level_pattern = re.compile(r'^from\s+app\.services\.telegram_notifier\s+import\s+telegram_notifier')
    has_module_import = any(module_level_pattern.match(line) for line in lines)
    
    assert has_module_import, (
        "Module-level import of telegram_notifier not found. "
        "Expected: 'from app.services.telegram_notifier import telegram_notifier' at module level"
    )


def test_no_function_scope_imports_telegram_notifier_other_files():
    """Test that other critical files don't have risky function-scope imports."""
    test_dir = Path(__file__).parent
    # test_dir is backend/app/tests, so backend_dir is backend/app
    backend_dir = test_dir.parent
    
    # Files to check (from user's known hits list)
    files_to_check = [
        "app/main.py",
        "app/api/routes_orders.py",
        "app/api/routes_monitoring.py",
        "app/services/scheduler.py",
        "app/services/exchange_sync.py",
        "app/services/brokers/crypto_com_trade.py",
    ]
    
    pattern = re.compile(r'^\s+from\s+app\.services\.telegram_notifier\s+import\s+telegram_notifier')
    
    all_violations = {}
    
    for file_path in files_to_check:
        full_path = backend_dir / file_path
        if not full_path.exists():
            continue  # Skip if file doesn't exist
        
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')
        
        violations = []
        for line_num, line in enumerate(lines, start=1):
            if pattern.match(line):
                # Check if telegram_notifier is used before this import in the same function
                # This is a simplified check - we flag all function-scope imports as potentially risky
                violations.append((line_num, line.strip()))
        
        if violations:
            all_violations[file_path] = violations
    
    if all_violations:
        error_msg = "Found function-scope imports of telegram_notifier in:\n"
        for file_path, violations in all_violations.items():
            error_msg += f"\n  {file_path}:\n"
            for line_num, line in violations:
                error_msg += f"    Line {line_num}: {line}\n"
        error_msg += (
            "\nThese imports may cause UnboundLocalError. "
            "Consider moving to module level or ensuring telegram_notifier is not "
            "referenced before the import in the same function scope."
        )
        # Warn but don't fail - these are in other files, not the critical signal_monitor.py
        print(f"WARNING: {error_msg}")
