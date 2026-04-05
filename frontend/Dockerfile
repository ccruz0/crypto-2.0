# ---------- 1) Dependencies ----------

FROM node:22-alpine AS deps

WORKDIR /app

RUN apk add --no-cache libc6-compat

COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts && npm cache clean --force

# ---------- 2) Builder ----------

FROM deps AS builder

WORKDIR /app

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---------- 3) Runner ----------

FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup -S app && adduser -S app -G app

COPY --from=builder /app/.next/standalone ./

COPY --from=builder /app/.next/static ./.next/static

COPY --from=builder /app/public ./public

EXPOSE 3000

# SECURITY: No wget in runtime - use node to avoid RCE payloads that rely on wget/curl
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/', (r)=>process.exit(r.statusCode===200?0:1)).on('error', ()=>process.exit(1));"]

USER app

CMD ["node", "server.js"]
