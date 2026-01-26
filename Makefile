.PHONY: test-signing test-local-signing aws-backend-up

aws-backend-up:
	@bash scripts/aws/aws_up_backend.sh

test-signing:
	bash scripts/dev/run_tests.sh

test-local-signing:
	PYTHONPATH=backend python3 -m pytest -q backend/tests/test_crypto_com_trade_signing.py
