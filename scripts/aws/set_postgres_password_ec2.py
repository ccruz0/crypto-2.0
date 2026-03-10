#!/usr/bin/env python3
"""
Prompt for Postgres password (popup on macOS, else terminal), then update
.env and .env.aws on EC2 with POSTGRES_PASSWORD and DATABASE_URL, and
force-recreate the backend container so it picks up the new env.

Usage (from repo root, with SSH key and EC2 reachable):
  python3 scripts/aws/set_postgres_password_ec2.py

Requires: EC2_HOST and SSH_KEY env vars, or defaults (see below).

Important: The password you enter must match what Postgres was initialized with.
If you still get "password authentication failed" after running this:
- The postgres_hardened volume may have been created earlier with a different
  POSTGRES_PASSWORD. Use that password when prompted, or (if you can afford to
  lose DB data) remove the volume and recreate: on EC2,
  docker compose --profile aws down; docker volume rm ... postgres_data; up -d
"""
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

# Defaults (override with env)
EC2_HOST = os.environ.get("EC2_HOST", "52.220.32.147")
SSH_USER = os.environ.get("SSH_USER", "ubuntu")
SSH_KEY = os.environ.get("SSH_KEY", os.path.expanduser("~/.ssh/atp-rebuild-2026.pem"))
REPO_PATH = os.environ.get("EC2_REPO_PATH", "/home/ubuntu/automated-trading-platform")


def get_password_gui_mac():
    """Use macOS osascript for a native password dialog."""
    script = '''
    display dialog "Postgres password for user 'trader' (EC2 .env):" ¬
        default answer "" with title "ATP EC2" with hidden answer
    return text returned of result
    '''
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if out.returncode != 0:
            return None
        return (out.stdout or "").strip()
    except Exception:
        return None


def get_password_terminal():
    """Fallback: prompt in terminal with hidden input."""
    try:
        import getpass
        return getpass.getpass("Postgres password for trader (EC2 .env): ").strip()
    except Exception:
        return None


def get_password():
    """Try GUI (Mac) first, then terminal."""
    if sys.platform == "darwin":
        p = get_password_gui_mac()
        if p is not None:
            return p
    return get_password_terminal()


def main():
    password = get_password()
    if not password:
        print("No password entered or dialog cancelled.", file=sys.stderr)
        sys.exit(1)

    encoded = urllib.parse.quote_plus(password)
    database_url = f"postgresql://trader:{encoded}@db:5432/atp"

    # Write snippet to a temp file (no newline in values)
    line1 = f"POSTGRES_PASSWORD={password}"
    line2 = f"DATABASE_URL={database_url}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write(line1 + "\n")
        f.write(line2 + "\n")
        tmp_path = f.name

    try:
        remote_tmp = "/tmp/atp_pg_env_snippet"
        # Upload snippet
        scp = subprocess.run(
            [
                "scp", "-i", SSH_KEY, "-o", "ConnectTimeout=15",
                tmp_path, f"{SSH_USER}@{EC2_HOST}:{remote_tmp}",
            ],
            capture_output=True,
            text=True,
        )
        if scp.returncode != 0:
            print("SCP failed:", scp.stderr or scp.stdout, file=sys.stderr)
            sys.exit(2)

        # On EC2: merge into .env and .env.aws (strip old POSTGRES_PASSWORD/DATABASE_URL, append new)
        merge_script = f"""
        set -e
        cd {REPO_PATH}
        for f in .env .env.aws; do
          [ -f "$f" ] || touch "$f"
          (grep -v '^POSTGRES_PASSWORD=' "$f" | grep -v '^DATABASE_URL=') > "$f.tmp" 2>/dev/null || true
          cat {remote_tmp} >> "$f.tmp"
          mv "$f.tmp" "$f"
        done
        rm -f {remote_tmp}
        echo "Updated .env and .env.aws with POSTGRES_PASSWORD and DATABASE_URL."
        """
        ssh = subprocess.run(
            [
                "ssh", "-i", SSH_KEY, "-o", "ConnectTimeout=15",
                f"{SSH_USER}@{EC2_HOST}", "bash", "-s",
            ],
            input=merge_script,
            capture_output=True,
            text=True,
        )
        if ssh.returncode != 0:
            print("SSH merge failed:", ssh.stderr or ssh.stdout, file=sys.stderr)
            sys.exit(3)
        print(ssh.stdout or "Done.")
    finally:
        os.unlink(tmp_path)

    print("Recreating backend container on EC2 so it picks up the new DATABASE_URL...")
    subprocess.run(
        [
            "ssh", "-i", SSH_KEY, "-o", "ConnectTimeout=15",
            f"{SSH_USER}@{EC2_HOST}",
            f"cd {REPO_PATH} && docker compose --profile aws up -d --force-recreate backend-aws",
        ],
        capture_output=True,
        text=True,
    )
    print("Done. Run bootstrap if needed: ssh ... './scripts/db/bootstrap.sh'")


if __name__ == "__main__":
    main()
