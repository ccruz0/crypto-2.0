.PHONY: test-signing test-local-signing aws-backend-up check-diagnose-auth aws-verify-exchange-creds verify-exchange-creds-local aws-fingerprint-creds aws-verify-auth-simple aws-auth-check local-fingerprint-creds local-verify-auth-simple

# Compile-check backend diagnostic script to prevent IndentationError regressions
check-diagnose-auth:
	@python3 -m py_compile backend/scripts/diagnose_auth_issue.py && echo "OK: diagnose_auth_issue.py compiles"

# Run exchange credential verification INSIDE the backend-aws container (use on AWS host)
aws-verify-exchange-creds:
	@docker compose --profile aws exec backend-aws python /app/scripts/verify_exchange_creds_runtime.py

# Run same script locally with local env vars (no Docker), for comparison with AWS fingerprint
verify-exchange-creds-local:
	@cd backend && PYTHONPATH=. python3 scripts/verify_exchange_creds_runtime.py

# Fingerprint creds only (safe: key/secret prefix-suffix + sha256[:10]); exit non-zero if missing
aws-fingerprint-creds:
	@docker compose --profile aws exec backend-aws python /app/scripts/fingerprint_creds.py

# Simple auth check: public get-tickers + private user-balance (same code path as production). Force AWS context.
aws-verify-auth-simple:
	@docker compose --profile aws exec -e EXECUTION_CONTEXT=AWS backend-aws python /app/scripts/verify_crypto_auth_simple.py

# Run Crypto.com auth check inside AWS container (alias for aws-verify-auth-simple)
aws-auth-check: aws-verify-auth-simple

# Run fingerprint locally (PYTHONPATH=backend) for comparison with AWS
local-fingerprint-creds:
	@cd backend && PYTHONPATH=. python3 scripts/fingerprint_creds.py

# Run simple auth check locally
local-verify-auth-simple:
	@cd backend && EXECUTION_CONTEXT=LOCAL PYTHONPATH=. python3 scripts/verify_crypto_auth_simple.py

aws-backend-up:
	@bash scripts/aws/aws_up_backend.sh

test-signing:
	bash scripts/dev/run_tests.sh

test-local-signing:
	PYTHONPATH=backend python3 -m pytest -q backend/tests/test_crypto_com_trade_signing.py
