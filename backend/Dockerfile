# ---------- 1) Builder: build wheels ----------
# Note: Using Python 3.11 due to aiohttp 3.8.2 (required by alpaca-trade-api) compatibility
# aiohttp 3.8.2 does not compile on Python 3.12

FROM python:3.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# SO deps mínimos para compilar wheels de algunas libs
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc curl libpq-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt

RUN pip install --upgrade pip wheel 'setuptools>=70.0.0' \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# (opcional) auditoría en build para evitar versiones con CVE graves, sin romper builds por dev deps
RUN pip install pip-audit && pip-audit -r requirements.txt || true

# ---------- 2) Runner: minimal runtime ----------
# Note: Using Python 3.11 due to aiohttp 3.8.2 (required by alpaca-trade-api) compatibility

FROM python:3.11-slim-bookworm AS runner

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UVICORN_WORKERS=1

WORKDIR /app

# Crear usuario no root
RUN useradd -m -u 10001 appuser

# Solo runtime deps desde wheels (excluyendo dev deps)
COPY --from=builder /wheels /wheels

# Copy requirements.txt for installation
COPY backend/requirements.txt ./requirements.txt

# Instalar solo dependencias de producción desde wheels
# (dev deps como pytest, black, isort, flake8 están comentadas en requirements.txt)
# First try from wheels, then fallback to PyPI if any package is missing
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt 2>&1 | tee /tmp/wheel_install.log || \
    (echo "WARNING: Some packages not found in wheels, installing from PyPI..." && \
     pip install --no-cache-dir -r requirements.txt)

# Ensure critical packages are installed (explicit verification)
# Verify pydantic-settings is installed (critical dependency)
RUN pip install --no-cache-dir pydantic-settings==2.5.2 && \
    python -c "import pydantic_settings; print('pydantic-settings installed successfully')" || \
    (echo "ERROR: pydantic-settings installation failed" && exit 1)

# Build fingerprint: capture git commit and build time
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown

# Copiar código de la app (needed before we can check .git)
# CRITICAL: Build context is "." (repo root), so we copy backend/ directory contents
COPY backend/ .

# Explicitly copy scripts directory to ensure it's included in the image
# This prevents regression if .dockerignore or COPY . . behavior changes
# CRITICAL: Build context must be "." (repo root) not "./backend" for this to work
COPY backend/scripts/ /app/scripts/

# Build-time assertions: fail loudly if required files/directories are missing
# This ensures the build fails immediately rather than silently missing files at runtime
RUN test -d /app/scripts || (echo "ERROR: /app/scripts directory is missing in image" >&2 && echo "DEBUG: Contents of /app:" >&2 && ls -la /app >&2 || true && exit 1)
RUN test -f /app/scripts/print_api_fingerprints.py || (echo "ERROR: /app/scripts/print_api_fingerprints.py is missing in image" >&2 && echo "DEBUG: Contents of /app/scripts:" >&2 && (ls -la /app/scripts >&2 || echo "/app/scripts does not exist" >&2) && exit 1)

# Auto-detect build fingerprint if not provided via build args
# After COPY . ., we can check .git directory and get current time
# Use shell to compute final values and write to files for later use
RUN FINAL_GIT_SHA="$GIT_SHA" && \
    if [ "$FINAL_GIT_SHA" = "unknown" ] && [ -d .git ] && command -v git >/dev/null 2>&1; then \
        FINAL_GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown"); \
    fi && \
    FINAL_BUILD_TIME="$BUILD_TIME" && \
    if [ "$FINAL_BUILD_TIME" = "unknown" ]; then \
        FINAL_BUILD_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ"); \
    fi && \
    echo "$FINAL_GIT_SHA" > /app/.git_sha && \
    echo "$FINAL_BUILD_TIME" > /app/.build_time

# Set environment variables - use ARG values as defaults
# If ARG was "unknown", the RUN command above wrote detected values to /app/.git_sha and /app/.build_time
# An entrypoint script will read those files and override env vars at runtime if needed
ENV ATP_GIT_SHA=${GIT_SHA} \
    ATP_BUILD_TIME=${BUILD_TIME}

# Copy entrypoint script and make it executable
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# FIX: Change ownership of /app to appuser so it can write trading_config.json
# This must be done as root before switching to appuser
RUN chown -R appuser:appuser /app

# Puerto y healthcheck
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import socket; s=socket.socket(); \
  s.settimeout(3); s.connect(('127.0.0.1',8002)); print('ok')" || exit 1

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
