# Rebuild, push and redeploy OpenClaw (gateway --bind lan)

The OpenClaw Dockerfile was updated to use `--bind lan` so the gateway listens on 0.0.0.0:18789 and is reachable from Nginx on PROD.

## 1. Build and push image (from your Mac)

**Start Docker Desktop** (or ensure the Docker daemon is running).

### Login to GHCR (required before push)

Create a GitHub Personal Access Token with `write:packages` (and `read:packages`):  
GitHub → Settings → Developer settings → Personal access tokens → Generate new token (classic).

Then:

```bash
docker login ghcr.io -u ccruz0 --password-stdin
```

Paste your token and press Enter. Or: `echo YOUR_TOKEN | docker login ghcr.io -u ccruz0 --password-stdin`

### Build and push

```bash
cd /Users/carloscruz/openclaw
docker build -t ghcr.io/ccruz0/openclaw:latest .
docker push ghcr.io/ccruz0/openclaw:latest
```

Alternatively, if you use GitHub Actions to build on push:

```bash
cd /Users/carloscruz/openclaw
git add Dockerfile
git commit -m "fix(docker): gateway --bind lan for proxy reachability"
git push origin main
```

Then wait for the workflow to build and push the image to GHCR.

## 2. Redeploy on LAB (SSM)

```bash
aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
```

Inside the LAB session:

```bash
sudo docker pull ghcr.io/ccruz0/openclaw:latest
sudo docker stop openclaw; sudo docker rm openclaw
sudo docker run -d --restart unless-stopped -p 8081:18789 --name openclaw ghcr.io/ccruz0/openclaw:latest
sudo docker logs openclaw --tail 20
```

In the logs you should see `listening on ws://0.0.0.0:18789` (not only 127.0.0.1).

## 3. Verify

- From LAB: `curl -s -m 3 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/` → should return 200 or 301.
- Browser: https://dashboard.hilovivo.com/openclaw/ → should load without 504.
