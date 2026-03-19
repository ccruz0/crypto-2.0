#!/usr/bin/env python3
"""
Forensic investigation: Find exact source of old Telegram /task response.

Target string: "This task has low impact and was not created"
Full message: "❌ Task creation failed: This task has low impact and was not created. If this is important, please clarify urgency or impact."

Run inside backend-aws container:
  docker compose --profile aws exec backend-aws python /app/scripts/diag/forensic_telegram_task_source.py

Or via SSM:
  aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec -T backend-aws python /app/scripts/diag/forensic_telegram_task_source.py"]' \
    --region ap-southeast-1
"""
from __future__ import annotations

import inspect
import os
import socket
import sys

# Ensure app is importable
sys.path.insert(0, "/app")

def main() -> None:
    print("=" * 70)
    print("FORENSIC: Telegram /task old message source investigation")
    print("=" * 70)

    # 1. Runtime identity
    print("\n--- 1. RUNTIME IDENTITY ---")
    print(f"hostname: {socket.gethostname()}")
    print(f"pid: {os.getpid()}")
    print(f"python: {sys.executable}")
    print(f"cwd: {os.getcwd()}")

    # Container ID from hostname or env
    container_id = os.environ.get("HOSTNAME", "N/A")
    print(f"container_id (HOSTNAME): {container_id}")

    # 2. Loaded module paths
    print("\n--- 2. LOADED MODULE PATHS ---")
    for mod_name in ("app.services.telegram_commands", "app.services.task_compiler"):
        try:
            mod = __import__(mod_name, fromlist=[""])
            path = getattr(mod, "__file__", "N/A")
            print(f"  {mod_name}: {path}")
        except Exception as e:
            print(f"  {mod_name}: IMPORT FAILED - {e}")

    # 3. Search for exact string in loaded source
    print("\n--- 3. SEARCH RUNTIME FILESYSTEM FOR OLD STRING ---")
    old_full = "This task has low impact and was not created"
    old_partial = "low impact and was not created"
    old_tail = "clarify urgency or impact"

    search_dirs = ["/app/app", "/app/backend/app", "/app/scripts"]
    found_in: list[tuple[str, int, str]] = []

    for root, _dirs, files in os.walk("/app"):
        # Skip __pycache__, .git, node_modules
        if "__pycache__" in root or ".git" in root or "node_modules" in root:
            continue
        for f in files:
            if not (f.endswith(".py") or f.endswith(".pyc") or f.endswith(".txt") or f.endswith(".sh")):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, "r", errors="replace") as fp:
                    for i, line in enumerate(fp, 1):
                        if old_full in line or old_partial in line or old_tail in line:
                            found_in.append((path, i, line.strip()[:120]))
            except (OSError, UnicodeDecodeError):
                pass

    if found_in:
        print("  FOUND in:")
        for path, line_no, preview in found_in:
            print(f"    {path}:{line_no}  {repr(preview)}")
    else:
        print("  NOT FOUND in /app (runtime filesystem)")

    # 4. Inspect runtime-loaded code
    print("\n--- 4. RUNTIME-LOADED CODE (inspect.getsource) ---")
    try:
        from app.services import telegram_commands as tc
        if hasattr(tc, "_handle_task_command"):
            src = inspect.getsource(tc._handle_task_command)
            # Check for old string in actual loaded source
            if old_partial in src or old_tail in src:
                print("  _handle_task_command CONTAINS old string!")
                for i, line in enumerate(src.splitlines(), 1):
                    if old_partial in line or old_tail in line:
                        print(f"    Line {i}: {line.strip()[:100]}")
            else:
                print("  _handle_task_command: old string NOT in loaded source")
            # Show error handling section
            if "result.get(\"error\"" in src:
                print("  _handle_task_command: uses result.get('error') - err comes from create_task_from_telegram_intent")
        else:
            print("  _handle_task_command: NOT FOUND")
    except Exception as e:
        print(f"  telegram_commands inspect FAILED: {e}")

    try:
        from app.services import task_compiler as tcomp
        if hasattr(tcomp, "create_task_from_telegram_intent"):
            src = inspect.getsource(tcomp.create_task_from_telegram_intent)
            if old_partial in src or old_tail in src:
                print("  create_task_from_telegram_intent CONTAINS old string!")
                for i, line in enumerate(src.splitlines(), 1):
                    if old_partial in line or old_tail in line:
                        print(f"    Line {i}: {line.strip()[:100]}")
            else:
                print("  create_task_from_telegram_intent: old string NOT in loaded source")
        else:
            print("  create_task_from_telegram_intent: NOT FOUND")
    except Exception as e:
        print(f"  task_compiler inspect FAILED: {e}")

    # 5. Check for .pyc / __pycache__
    print("\n--- 5. PYC FILES WITH OLD STRING (grep in __pycache__) ---")
    pycache_root = "/app/app/services/__pycache__"
    if os.path.isdir(pycache_root):
        for name in os.listdir(pycache_root):
            if name.endswith(".pyc"):
                path = os.path.join(pycache_root, name)
                try:
                    with open(path, "rb") as fp:
                        data = fp.read()
                    if old_partial.encode() in data or old_tail.encode() in data:
                        print(f"  FOUND in {path}")
                    else:
                        pass  # not found
                except Exception:
                    pass
        print("  (binary check done - string in .pyc would indicate stale bytecode)")
    else:
        print("  __pycache__ not found")

    # 6. Mounted volumes that could override
    print("\n--- 6. BIND MOUNTS / VOLUMES (docker inspect) ---")
    print("  Run on host: docker inspect <container> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{\"\\n\"}}{{end}}'")

    # 7. Git SHA in image
    git_sha_path = "/app/.git_sha"
    if os.path.isfile(git_sha_path):
        with open(git_sha_path) as f:
            sha = f.read().strip()
        print(f"\n--- 7. IMAGE GIT SHA ---")
        print(f"  {git_sha_path}: {sha}")

    print("\n" + "=" * 70)
    print("CONCLUSION: If old string NOT in runtime source, it comes from:")
    print("  - Stale image (rebuild with --no-cache)")
    print("  - Different container/process (canary, another instance)")
    print("  - Different bot token (another runtime)")
    print("=" * 70)


if __name__ == "__main__":
    main()
