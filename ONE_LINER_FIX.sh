#!/bin/bash
# One-liner to apply authentication fix on AWS server
# Run this on your AWS server: bash ONE_LINER_FIX.sh

cd ~/automated-trading-platform && \
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws && \
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws && \
echo "✅ Added to .env.aws" && \
docker compose restart backend && \
echo "✅ Backend restarted" && \
sleep 5 && \
echo "✅ Checking logs..." && \
docker compose logs backend --tail 50 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 && \
echo "" && \
echo "✅ Fix applied! Monitor logs for next order: docker compose logs backend -f | grep -E 'AUTHENTICATION|order created'"

