# OpenClaw container

Placeholder image that listens on **port 8080** for the LAB. Replaces the need for `ghcr.io/your-org/openclaw:latest` until a full OpenClaw app image is available.

## Image

- **Built by CI:** On push to `main` (when `openclaw/` or this workflow changes), GitHub Actions builds and pushes:
  - `ghcr.io/<owner>/<repo>:openclaw`  
  Example for repo `ccruz0/crypto-2.0`: **`ghcr.io/ccruz0/crypto-2.0:openclaw`**

## Use on LAB

In `.env.lab`:

```bash
OPENCLAW_IMAGE=ghcr.io/ccruz0/crypto-2.0:openclaw
```

Then:

```bash
docker compose -f docker-compose.openclaw.yml up -d
```

If the repo is under another org/user, replace with your `owner/repo` (e.g. `ghcr.io/MYORG/crypto-2.0:openclaw`). The package is tied to the GitHub repo; make it **Public** in Package settings if the LAB pulls without login.

## Build locally

```bash
docker build -t ghcr.io/ccruz0/openclaw:latest -f openclaw/Dockerfile .
```

## Trigger build manually

In GitHub: **Actions** → **Build OpenClaw image** → **Run workflow**.
