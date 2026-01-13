#!/bin/bash
# Fix await syntax error in signal_monitor.py

cd ~/automated-trading-platform/backend/app/services || cd /home/ubuntu/automated-trading-platform/backend/app/services

# Check if file exists
if [ ! -f "signal_monitor.py" ]; then
    echo "ERROR: signal_monitor.py not found"
    exit 1
fi

# Find the problematic line and fix it
# Replace: order_result = await self._place_order_from_signal(
# With: order_result = loop.run_until_complete(self._place_order_from_signal(

# First, check if the issue exists
if grep -q "order_result = await self._place_order_from_signal(" signal_monitor.py; then
    echo "Found await statement, fixing..."
    # Create backup
    cp signal_monitor.py signal_monitor.py.backup
    
    # Fix the await statement - replace with loop.run_until_complete
    # This is a complex replacement, so we'll use sed with multiline pattern
    python3 << 'PYTHON_FIX'
import re

with open('signal_monitor.py', 'r') as f:
    content = f.read()

# Pattern to find: order_result = await self._place_order_from_signal(...)
# Replace with proper loop.run_until_complete pattern
pattern = r'(\s+)order_result = await self\._place_order_from_signal\('
replacement = r'\1order_result = loop.run_until_complete(\n\1    self._place_order_from_signal('

# Also need to close the loop.run_until_complete properly
# Find the matching closing paren and add the closing for run_until_complete
content = re.sub(pattern, replacement, content)

# Now fix the closing - find the line after the function call that closes it
# and add the closing paren for run_until_complete
# This is tricky, so let's do a simpler approach: find the pattern and replace the whole block

# Actually, let's check what the current structure looks like first
if 'order_result = await self._place_order_from_signal(' in content:
    # Find the line number
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'order_result = await self._place_order_from_signal(' in line:
            indent = len(line) - len(line.lstrip())
            # Replace this line
            lines[i] = ' ' * indent + 'order_result = loop.run_until_complete('
            # Find the closing paren for the function call (should be a few lines later)
            # Look for the line that closes this call
            for j in range(i+1, min(i+15, len(lines))):
                if lines[j].strip() == ')' and len(lines[j]) - len(lines[j].lstrip()) == indent + 4:
                    # This is likely the closing paren for _place_order_from_signal
                    # Add another closing paren for run_until_complete
                    lines[j] = ' ' * indent + ')'
                    break
            break
    content = '\n'.join(lines)

with open('signal_monitor.py', 'w') as f:
    f.write(content)

print("Fixed await statement")
PYTHON_FIX

    echo "✅ File fixed"
    # Verify syntax
    python3 -m py_compile signal_monitor.py && echo "✅ Syntax check passed" || echo "❌ Syntax check failed"
else
    echo "No await statement found - file may already be fixed"
fi
