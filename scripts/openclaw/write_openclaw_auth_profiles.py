#!/usr/bin/env python3
"""Write OpenClaw agent auth-profiles.json from env vars and/or home-data/.env."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import sys


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def main() -> int:
    home = pathlib.Path(os.environ.get("OPENCLAW_HOME_DIR", "/opt/openclaw/home-data"))
    file_vals = _parse_env_file(home / ".env")
    openai = os.environ.get("OPENAI_API_KEY", "").strip() or file_vals.get("OPENAI_API_KEY", "").strip()
    anthropic = os.environ.get("ANTHROPIC_API_KEY", "").strip() or file_vals.get(
        "ANTHROPIC_API_KEY", ""
    ).strip()

    profiles: dict[str, dict[str, str]] = {}
    if openai:
        profiles["openai:default"] = {"type": "api_key", "api_key": openai}
    if anthropic:
        profiles["anthropic:default"] = {"type": "api_key", "api_key": anthropic}

    if not profiles:
        print(
            "write_openclaw_auth_profiles: no OPENAI_API_KEY or ANTHROPIC_API_KEY "
            f"(set env or add to {home / '.env'})",
            file=sys.stderr,
        )
        return 1

    agent_dir = home / "agents" / "main" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    out_path = agent_dir / "auth-profiles.json"
    payload = {"version": 1, "profiles": profiles}
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    out_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    uid = int(os.environ.get("OPENCLAW_AUTH_UID", "1000"))
    gid = int(os.environ.get("OPENCLAW_AUTH_GID", "1000"))
    try:
        os.chown(out_path, uid, gid)
    except PermissionError:
        print(
            f"Warning: could not chown {out_path} to {uid}:{gid}; run with sudo if needed",
            file=sys.stderr,
        )
    print(f"Wrote {out_path} providers={','.join(profiles.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
