.PHONY: lock build run verify-backend-image

lock:
	bash scripts/lock.sh

build:
	docker build --no-cache -t automated-trading-platform-backend:latest .

run:
	docker run --rm -p 8000:8000 automated-trading-platform-backend:latest

verify-backend-image:
	@echo "Verifying backend image contains required scripts..."
	@docker run --rm automated-trading-platform-backend:latest sh -c "test -f /app/scripts/print_api_fingerprints.py && echo '✅ OK: print_api_fingerprints.py exists' || (echo '❌ FAIL: print_api_fingerprints.py missing' && exit 1)"
