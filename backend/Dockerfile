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

COPY requirements.txt ./requirements.txt

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
COPY requirements.txt ./requirements.txt

# Instalar solo dependencias de producción desde wheels
# (dev deps como pytest, black, isort, flake8 están comentadas en requirements.txt)
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt

# Build fingerprint: capture git commit and build time
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV ATP_GIT_SHA=${GIT_SHA} \
    ATP_BUILD_TIME=${BUILD_TIME}

# Copiar código de la app
COPY . .

# FIX: Change ownership of /app to appuser so it can write trading_config.json
# This must be done as root before switching to appuser
RUN chown -R appuser:appuser /app

# Puerto y healthcheck
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import socket; s=socket.socket(); \
  s.settimeout(3); s.connect(('127.0.0.1',8002)); print('ok')" || exit 1

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
