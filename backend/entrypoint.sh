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
fi

if [ -f /app/secrets/runtime.env ]; then
  set -a
  . /app/secrets/runtime.env
  set +a
fi

# If ATP_GIT_SHA is "unknown" and we have a detected value in file, use it
if [ "$ATP_GIT_SHA" = "unknown" ] && [ -f /app/.git_sha ]; then
    DETECTED_SHA=$(cat /app/.git_sha 2>/dev/null | tr -d '\n')
    if [ -n "$DETECTED_SHA" ] && [ "$DETECTED_SHA" != "unknown" ]; then
        export ATP_GIT_SHA="$DETECTED_SHA"
    fi
fi

# If ATP_BUILD_TIME is "unknown" and we have a detected value in file, use it
if [ "$ATP_BUILD_TIME" = "unknown" ] && [ -f /app/.build_time ]; then
    DETECTED_TIME=$(cat /app/.build_time 2>/dev/null | tr -d '\n')
    if [ -n "$DETECTED_TIME" ] && [ "$DETECTED_TIME" != "unknown" ]; then
        export ATP_BUILD_TIME="$DETECTED_TIME"
    fi
fi

# Execute the original command (as appuser if we are root, for security)
if [ "$(id -u)" = "0" ]; then
  exec gosu appuser "$@"
else
  exec "$@"
fi

