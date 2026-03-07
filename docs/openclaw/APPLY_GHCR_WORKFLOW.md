# Aplicar workflow de build y publicación a GHCR (repo OpenClaw)

Este runbook es para usar **dentro del repositorio ccruz0/openclaw**. El workflow construye y publica la imagen Docker en GitHub Container Registry sin necesidad de Docker local.

## Objetivo

- **Imagen:** `ghcr.io/ccruz0/openclaw:latest`
- **Disparadores:** push a `main` y ejecución manual (`workflow_dispatch`)

## Pasos en el repo ccruz0/openclaw

1. **Crear el workflow**

   En la raíz del repo openclaw, crea el archivo:

   `.github/workflows/docker_publish.yml`

   Contenido (el mismo que en `docs/openclaw/.github/workflows/docker_publish.yml` de ATP):

   ```yaml
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
   ```

2. **Commit y push**

   ```bash
   git add .github/workflows/docker_publish.yml
   git commit -m "ci: add GHCR build and publish workflow"
   git push origin main
   ```

3. **Comprobar en GitHub**

   - Ve a **Actions** del repo openclaw y espera a que termine el workflow.
   - Verifica que la imagen exista en **Packages** (GHCR): `ghcr.io/ccruz0/openclaw:latest`.

## Redesplegar el contenedor en LAB

En el servidor LAB (donde corre OpenClaw):

```bash
docker pull ghcr.io/ccruz0/openclaw:latest
docker stop openclaw || true
docker rm openclaw || true
docker run -d --restart unless-stopped -p 8081:8081 --name openclaw ghcr.io/ccruz0/openclaw:latest
```

## Resultado esperado

- Build automático en cada `git push` a `main`.
- Push automático a GHCR.
- No hace falta Docker en la Mac; todo en GitHub Actions.
- Imagen lista para usar: `ghcr.io/ccruz0/openclaw:latest`.
