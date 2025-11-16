.PHONY: lock build run

lock:
	bash scripts/lock.sh

build:
	docker build --no-cache -t automated-trading-platform-backend:latest .

run:
	docker run --rm -p 8000:8000 automated-trading-platform-backend:latest
