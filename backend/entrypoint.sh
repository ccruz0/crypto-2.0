#!/bin/sh
# Entrypoint script to set build fingerprint env vars from detected values if ARG was "unknown"

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

# Execute the original command
exec "$@"

