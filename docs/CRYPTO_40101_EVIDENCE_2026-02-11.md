# Crypto.com 40101 Evidence — 2026-02-11 (AWS)

## B.1 Fingerprint (safe)
```bash
cd /home/ubuntu/crypto-2.0
git rev-parse HEAD
git status -sb
docker compose --profile aws ps
docker images | head -n 30
docker compose --profile aws exec -T backend-aws sh -lc 'env | egrep "EXCHANGE_|CRYPTO_|LIVE_TRADING|USE_CRYPTO_PROXY|REST_BASE|EXCHANGE_CUSTOM_BASE_URL" | sed "s/=.*$/=(redacted)/" | sort'
