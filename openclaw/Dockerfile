# OpenClaw placeholder image — serves a minimal UI on 8080 for LAB.
# Replace with a full OpenClaw app image when available.
# Build: docker build -t ghcr.io/ccruz0/openclaw:latest -f openclaw/Dockerfile .
FROM python:3.11-slim-bookworm

WORKDIR /app
RUN useradd -m -u 1000 appuser

# Serve on 8080 (read-only, no write)
EXPOSE 8080
ENV PORT=8080

# Minimal HTTP server that listens on 0.0.0.0:8080
RUN echo 'import http.server; import os; os.chdir("/app"); http.server.HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), http.server.SimpleHTTPRequestHandler).serve_forever()' > /app/server.py

# Static placeholder page
RUN echo '<!DOCTYPE html><html><head><title>OpenClaw</title></head><body><h1>OpenClaw</h1><p>Placeholder. Replace OPENCLAW_IMAGE with full app when ready.</p></body></html>' > /app/index.html

USER appuser
CMD ["python", "-u", "/app/server.py"]
