#!/usr/bin/env python3
"""OpenClaw update daemon — runs on LAB host.

Listens for POST /update from the OpenClaw container (via host.docker.internal).
Verifies gateway.auth.token, then runs docker compose pull + up -d.

Requires: ubuntu user in docker group, openclaw.json with gateway.auth.token.
Install: see scripts/openclaw/install_openclaw_update_daemon.sh
"""
import json
import logging
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

CONFIG_PATH = os.environ.get("OPENCLAW_CONFIG_PATH", "/opt/openclaw/home-data/openclaw.json")
REPO_DIR = os.environ.get("ATP_REPO_PATH", "/home/ubuntu/crypto-2.0")
COMPOSE_FILE = "docker-compose.openclaw.yml"
PORT = int(os.environ.get("OPENCLAW_UPDATE_PORT", "19999"))
HOST = os.environ.get("OPENCLAW_UPDATE_HOST", "0.0.0.0")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [openclaw-update] %(message)s")
logger = logging.getLogger(__name__)


def get_gateway_token():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return (cfg.get("gateway", {}).get("auth", {}).get("token") or "").strip()
    except Exception as e:
        logger.warning("Failed to read gateway token: %s", e)
        return None


class UpdateHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/update":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')
            return

        token = get_gateway_token()
        if not token:
            logger.warning("No gateway token in config")
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"no_token"}')
            return

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"missing_auth"}')
            return

        if auth.split(" ", 1)[1].strip() != token:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"invalid_token"}')
            return

        logger.info("Update requested, running docker compose pull + up -d")
        try:
            os.chdir(REPO_DIR)
            subprocess.run(
                ["docker", "compose", "-f", COMPOSE_FILE, "pull", "--quiet"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Update completed")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","message":"updated"}')
        except subprocess.CalledProcessError as e:
            logger.error("Update failed: %s", e)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "error", "message": str(e)}).encode()
            )

    def do_GET(self):
        if urlparse(self.path).path.rstrip("/") == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"method_not_allowed"}')


def main():
    server = HTTPServer((HOST, PORT), UpdateHandler)
    logger.info("OpenClaw update daemon listening on %s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
