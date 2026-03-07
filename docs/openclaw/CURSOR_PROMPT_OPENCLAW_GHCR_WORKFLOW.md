# Prompt: GitHub Actions para build y push de la imagen a GHCR

**Pegar en Cursor con el repo ccruz0/openclaw abierto.**  
Crea un workflow que construya y publique la imagen en GHCR en cada push a main (o manual), sin usar Docker local.

---

## Prompt (copiar y pegar tal cual)

```
You are working inside the repository ccruz0/openclaw.

Goal: create a GitHub Actions workflow that automatically builds and publishes the Docker image for OpenClaw to GHCR.

Target image:
ghcr.io/ccruz0/openclaw:latest

Requirements:
1. Create workflow file

Create:

.github/workflows/docker_publish.yml

2. Workflow triggers

The workflow must run on:
- push to main
- manual trigger (workflow_dispatch)

3. Workflow behavior

Steps must:
- checkout repository
- login to GitHub Container Registry
- build Docker image
- push Docker image

4. Use official actions

Use:

actions/checkout@v4
docker/setup-buildx-action@v3
docker/login-action@v3
docker/build-push-action@v5

5. Image configuration

Repository:

ghcr.io/ccruz0/openclaw

Tags:

latest

6. Workflow content

Generate this workflow:

name: Build and Publish OpenClaw Image

on:
  push:
    branches: [ main ]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build-and-publish:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/ccruz0/openclaw:latest

7. Verification instructions

After creating the workflow:
- commit and push to main
- wait for GitHub Actions to complete
- verify image exists in GHCR

Expected result:

ghcr.io/ccruz0/openclaw:latest

8. Output

Provide:
- file created
- commit message suggestion
- command to redeploy container on LAB server

Redeploy command:

docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

---

## Resultado

- Build automático en cada push a main (o al disparar el workflow a mano).
- Push automático a GHCR.
- No hace falta Docker en tu Mac.
- Cada `git push` a main genera una nueva imagen `ghcr.io/ccruz0/openclaw:latest`.

---

## Redeploy en LAB (después de que Actions termine)

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

---

## Siguiente paso opcional

Hay un **tercer prompt** que elimina el placeholder del Dockerfile de ATP (origen del texto que se ve en /openclaw cuando se sirve la imagen antigua). Pídelo si quieres aplicarlo en el repo automated-trading-platform.
