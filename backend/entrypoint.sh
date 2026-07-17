#!/bin/sh
# Entrypoint script to set build fingerprint env vars from detected values if ARG was "unknown"
# Also sources secrets/runtime.env so the Python process reliably gets GITHUB_TOKEN and other
# deploy secrets (Docker env_file can have ordering/override issues; explicit source is authoritative).
#
# If running as root: ensure docs/agents/generated-notes exists and is writable by appuser
# (volume mount ./docs:/app/docs can have host ownership; app runs as appuser).
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/docs/agents/generated-notes
  chown -R appuser:appuser /app/docs/agents/generated-notes 2>/dev/null || true
  chmod 775 /app/docs/agents/generated-notes 2>/dev/null || true

  # Persist trading_config on the compose volume (TRADING_CONFIG_PATH=/data/...).
  # Docker named volumes are often root-owned; appuser must read/write the file.
  if [ -n "${TRADING_CONFIG_PATH:-}" ]; then
    _tc_dir=$(dirname "$TRADING_CONFIG_PATH")
    mkdir -p "$_tc_dir" 2>/dev/null || true
    # Seed volume from baked image config when missing (keeps coin presets across recreates).
    if [ ! -f "$TRADING_CONFIG_PATH" ] && [ -f /app/trading_config.json ]; then
      cp -a /app/trading_config.json "$TRADING_CONFIG_PATH" 2>/dev/null || true
    fi
    chown -R appuser:appuser "$_tc_dir" 2>/dev/null || true
    if [ -f "$TRADING_CONFIG_PATH" ]; then
      chown appuser:appuser "$TRADING_CONFIG_PATH" 2>/dev/null || true
      chmod 664 "$TRADING_CONFIG_PATH" 2>/dev/null || true
    fi
  fi
fi

if [ -f /app/secrets/runtime.env ]; then
  # Host-mounted secrets may be ubuntu:root 640; gunicorn workers run as appuser and
  # pydantic also opens secrets/runtime.env directly — ensure group-readable.
  if [ "$(id -u)" = "0" ]; then
    chown root:appuser /app/secrets/runtime.env 2>/dev/null || true
    chmod 640 /app/secrets/runtime.env 2>/dev/null || true
  fi
  set -a
  . /app/secrets/runtime.env
  set +a
fi

# If ATP_GIT_SHA is missing/unknown and we have a detected value in file, use it
if [ -z "$ATP_GIT_SHA" ] || [ "$ATP_GIT_SHA" = "unknown" ]; then
    if [ -f /app/.git_sha ]; then
        DETECTED_SHA=$(cat /app/.git_sha 2>/dev/null | tr -d '\n')
        if [ -n "$DETECTED_SHA" ] && [ "$DETECTED_SHA" != "unknown" ]; then
            export ATP_GIT_SHA="$DETECTED_SHA"
        fi
    fi
fi

# If ATP_BUILD_TIME is missing/unknown and we have a detected value in file, use it
if [ -z "$ATP_BUILD_TIME" ] || [ "$ATP_BUILD_TIME" = "unknown" ]; then
    if [ -f /app/.build_time ]; then
        DETECTED_TIME=$(cat /app/.build_time 2>/dev/null | tr -d '\n')
        if [ -n "$DETECTED_TIME" ] && [ "$DETECTED_TIME" != "unknown" ]; then
            export ATP_BUILD_TIME="$DETECTED_TIME"
        fi
    fi
fi

# Execute the original command (as appuser if we are root, for security)
if [ "$(id -u)" = "0" ]; then
  exec gosu appuser "$@"
else
  exec "$@"
fi

