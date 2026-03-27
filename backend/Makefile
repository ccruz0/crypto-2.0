.PHONY: lock build run verify-backend-image dev-up dev-logs dev-restart dev-down

lock:
	bash scripts/lock.sh

build:
	docker build --no-cache -t automated-trading-platform-backend:latest .

run:
	docker run --rm -p 8000:8000 automated-trading-platform-backend:latest

verify-backend-image:
	@echo "Verifying backend image contains required scripts..."
	@docker run --rm automated-trading-platform-backend:latest sh -c "test -f /app/scripts/print_api_fingerprints.py && echo '✅ OK: print_api_fingerprints.py exists' || (echo '❌ FAIL: print_api_fingerprints.py missing' && exit 1)"

# ============================================
# Local Development Commands (Hot Reload)
# ============================================
# Start db + backend-dev for fast hot-reload development
dev-up:
	@echo "🚀 Starting local dev environment (db + backend-dev)..."
	@cd ~/crypto-2.0 && docker compose --profile local up -d --build db backend-dev

# Tail logs from backend-dev
dev-logs:
	@echo "📋 Tailing backend-dev logs (Ctrl+C to exit)..."
	@cd ~/crypto-2.0 && docker compose --profile local logs -f backend-dev

# Restart backend-dev service
dev-restart:
	@echo "🔄 Restarting backend-dev..."
	@cd ~/crypto-2.0 && docker compose --profile local restart backend-dev

# Stop backend-dev (keeps db running)
dev-down:
	@echo "🛑 Stopping backend-dev..."
	@cd ~/crypto-2.0 && docker compose --profile local stop backend-dev
