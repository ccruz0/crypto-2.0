# Fix: "non-loopback Control UI requires gateway.controlUi.allowedOrigins"

**Apply this in the OpenClaw repository** (the one that builds `ghcr.io/ccruz0/openclaw:latest`), e.g. `ccruz0/openclaw`.

When the container runs behind a reverse proxy (e.g. Nginx at `https://dashboard.hilovivo.com/openclaw`), the gateway fails to start with:

```text
non-loopback Control UI requires gateway.controlUi.allowedOrigins
```

This runbook adds proper `allowedOrigins` support so the gateway starts correctly without disabling security checks.

---

## 1. Locate gateway configuration

In the **OpenClaw repo root**, run:

```bash
grep -Rn "controlUi\|allowedOrigins\|control\.ui\|gateway\.control" --include="*.ts" --include="*.js" --include="*.mjs" .
grep -Rn "openclaw\.json\|\.openclaw" --include="*.ts" --include="*.js" --include="*.mjs" .
grep -Rn "18789\|gateway" --include="*.ts" --include="*.js" --include="*.mjs" . | head -80
```

**Likely locations:**

- `openclaw.mjs` (or `openclaw.js`) — main entry / gateway bootstrap
- `src/gateway/*` — gateway server and config
- Any config loader that reads JSON or env (e.g. `loadConfig`, `getConfig`)
- Default config object or schema (e.g. `defaultConfig`, `configSchema`)

Note the file and symbol that:
- Start the gateway / HTTP/WS server
- Validate or use `controlUi` or `allowedOrigins`
- Read from a config file or env

---

## 2. Default allowedOrigins and config source

**Required behavior:**

- **Default** `gateway.controlUi.allowedOrigins` when not set:
  ```json
  [
    "https://dashboard.hilovivo.com",
    "http://localhost:18789",
    "http://127.0.0.1:18789"
  ]
  ```
- **Config file:** `~/.openclaw/openclaw.json` may define `gateway.controlUi.allowedOrigins` (array of strings).
- **Env override:** If `OPENCLAW_ALLOWED_ORIGINS` is set, it **overrides** the config file. Format: comma-separated list, e.g.  
  `OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789`
- **Auto-create config:** If `~/.openclaw/openclaw.json` does not exist, the app should create `~/.openclaw` and write a default `openclaw.json` with these sane defaults (including `gateway.controlUi.allowedOrigins`), then use it.

**Do not:** disable security checks or set `dangerouslyAllowHostHeaderOriginFallback`. Use `allowedOrigins` only.

---

## 3. Implementation sketch (apply in OpenClaw repo)

### 3.1 Default config

Define a default config object that includes:

```js
const DEFAULT_ALLOWED_ORIGINS = [
  "https://dashboard.hilovivo.com",
  "http://localhost:18789",
  "http://127.0.0.1:18789",
];

const defaultConfig = {
  // ... other defaults ...
  gateway: {
    controlUi: {
      allowedOrigins: [...DEFAULT_ALLOWED_ORIGINS],
    },
  },
};
```

### 3.2 Config file path and auto-create

- Config path: `~/.openclaw/openclaw.json` (resolve `~` with `os.homedir()` or `process.env.HOME`).
- On first load, if the file does not exist:
  - Create directory `~/.openclaw` if needed (`fs.mkdirSync(path.join(homedir, '.openclaw'), { recursive: true })`).
  - Write default JSON to `~/.openclaw/openclaw.json` (include `gateway.controlUi.allowedOrigins` in the default object).
- Then read config from that file and merge with defaults (file overrides defaults; do not require every key in the file).

### 3.3 Env override

After loading from file (and defaults), apply env:

- If `process.env.OPENCLAW_ALLOWED_ORIGINS` is set (non-empty string):
  - Split by comma: `process.env.OPENCLAW_ALLOWED_ORIGINS.split(',').map(s => s.trim()).filter(Boolean)`.
  - Set `config.gateway.controlUi.allowedOrigins = that array` (overrides file and default).

### 3.4 Pass to gateway

Ensure the gateway startup code receives the merged config and uses `config.gateway.controlUi.allowedOrigins` when starting the Control UI (e.g. passed into the server or middleware that checks the `Origin` header). The exact property name depends on the gateway API (e.g. `controlUi.allowedOrigins` or `allowedOrigins` in an options object).

---

## 4. Example: Node/JS config loader

If the repo uses a simple Node config loader, you can add a module like this (adapt paths and export style to the repo):

```js
// config.js or src/config.js
const fs = require('fs');
const path = require('path');
const os = require('os');

const DEFAULT_ALLOWED_ORIGINS = [
  'https://dashboard.hilovivo.com',
  'http://localhost:18789',
  'http://127.0.0.1:18789',
];

const defaultConfig = {
  gateway: {
    controlUi: {
      allowedOrigins: [...DEFAULT_ALLOWED_ORIGINS],
    },
  },
};

function getConfigPath() {
  const homedir = os.homedir();
  return path.join(homedir, '.openclaw', 'openclaw.json');
}

function ensureConfigDir() {
  const dir = path.join(os.homedir(), '.openclaw');
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return dir;
}

function loadConfig() {
  const configPath = getConfigPath();
  let fileConfig = {};
  if (fs.existsSync(configPath)) {
    try {
      fileConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (e) {
      console.warn('Could not parse openclaw.json, using defaults:', e.message);
    }
  } else {
    ensureConfigDir();
    const initial = JSON.parse(JSON.stringify(defaultConfig));
    try {
      fs.writeFileSync(configPath, JSON.stringify(initial, null, 2), 'utf8');
    } catch (e) {
      console.warn('Could not write default openclaw.json:', e.message);
    }
  }

  const merged = deepMerge(defaultConfig, fileConfig);

  if (process.env.OPENCLAW_ALLOWED_ORIGINS) {
    const origins = process.env.OPENCLAW_ALLOWED_ORIGINS
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);
    if (origins.length) {
      if (!merged.gateway) merged.gateway = {};
      if (!merged.gateway.controlUi) merged.gateway.controlUi = {};
      merged.gateway.controlUi.allowedOrigins = origins;
    }
  }

  return merged;
}

function deepMerge(target, source) {
  const out = { ...target };
  for (const key of Object.keys(source)) {
    if (source[key] != null && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      out[key] = deepMerge(out[key] || {}, source[key]);
    } else {
      out[key] = source[key];
    }
  }
  return out;
}

module.exports = { loadConfig, getConfigPath, DEFAULT_ALLOWED_ORIGINS };
```

Then in the gateway startup (e.g. `openclaw.mjs` or `src/gateway/server.js`):

- Call `loadConfig()` (or equivalent).
- Pass `config.gateway.controlUi.allowedOrigins` into the gateway/Control UI so the "non-loopback Control UI requires gateway.controlUi.allowedOrigins" check is satisfied.

---

## 5. Docker and environment

- **Dockerfile / entrypoint:** No need to disable security. Ensure the process can read `OPENCLAW_ALLOWED_ORIGINS` (standard env). Optionally ensure `~/.openclaw` is writable if you want auto-creation inside the container (e.g. a VOLUME or writeable path). If the container runs read-only, rely on env only and ensure defaults or env are always set.
- **docker run:** Pass the env var when deploying behind a proxy:
  ```bash
  docker run -d \
    -p 8081:18789 \
    -e OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com,http://localhost:18789 \
    --name openclaw \
    ghcr.io/ccruz0/openclaw:latest
  ```
- **docker-compose:** In the service, add:
  ```yaml
  environment:
    - OPENCLAW_ALLOWED_ORIGINS=${OPENCLAW_ALLOWED_ORIGINS:-https://dashboard.hilovivo.com,http://localhost:18789}
  ```
  (Or set `OPENCLAW_ALLOWED_ORIGINS` in `.env.lab`.)

---

## 6. Verification

1. **Local (loopback):** Start the app without proxy; it should still start (allowedOrigins can include localhost).
2. **Behind proxy:** Set `OPENCLAW_ALLOWED_ORIGINS=https://dashboard.hilovivo.com` (and optionally `http://localhost:18789`), run the container with `-p 8081:18789`, and confirm the gateway starts without "non-loopback Control UI requires gateway.controlUi.allowedOrigins".
3. **Config file:** If you create `~/.openclaw/openclaw.json` with a different `gateway.controlUi.allowedOrigins`, the app should use it unless `OPENCLAW_ALLOWED_ORIGINS` is set (env wins).

---

## 7. Summary checklist

- [ ] Locate gateway config (openclaw.mjs, src/gateway/*, config loader).
- [ ] Add default `gateway.controlUi.allowedOrigins` (dashboard.hilovivo.com, localhost:18789, 127.0.0.1:18789).
- [ ] Read from `~/.openclaw/openclaw.json`; create file with defaults if missing.
- [ ] Override with `OPENCLAW_ALLOWED_ORIGINS` (comma-separated) when set.
- [ ] Pass `allowedOrigins` into the gateway so the non-loopback check passes.
- [ ] Update Docker docs and compose to pass `-e OPENCLAW_ALLOWED_ORIGINS` where needed.
- [ ] Do not disable security or use `dangerouslyAllowHostHeaderOriginFallback`.

After applying in the OpenClaw repo, rebuild the image, push to GHCR, and redeploy the container with the env var set (see ATP repo `docker-compose.openclaw.yml` and runbooks).
