#!/usr/bin/env bash
# Classify why Bedrock invoke fails. Does not print secrets. Does not change IAM.
#
#   AWS_PROFILE=carlos-sso ./scripts/aws/probe_bedrock_account_status.sh
#
# account_restriction (Operation not allowed) can only be lifted by AWS Support.
set -euo pipefail

REGION="${JARVIS_BEDROCK_REGION:-${AWS_REGION:-us-east-1}}"
MODEL_ID="${JARVIS_BEDROCK_MODEL_ID:-anthropic.claude-3-sonnet-20240229-v1:0}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"

echo "=== Bedrock account probe ==="
echo "Profile: $AWS_PROFILE  Region: $REGION  Model: $MODEL_ID"
echo ""

if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"
echo ""

echo "=== list-foundation-models ($REGION) ==="
if OUT=$(aws bedrock list-foundation-models --region "$REGION" --query 'length(modelSummaries)' --output text 2>&1); then
  echo "list_ok count=$OUT"
else
  echo "list_failed"
  echo "$OUT" | head -c 500
  echo
fi
echo ""

echo "=== invoke_model (16 tokens, no prompt secrets) ==="
python3 - "$REGION" "$MODEL_ID" <<'PY'
import json, sys
region, model_id = sys.argv[1], sys.argv[2]
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError as e:
    print("FAIL: boto3 missing", e)
    raise SystemExit(1)

body = json.dumps({
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 16,
    "messages": [{"role": "user", "content": [{"type": "text", "text": "Reply: ping"}]}],
})
try:
    client = boto3.client("bedrock-runtime", region_name=region)
    resp = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    payload = json.loads(resp["body"].read())
    text = "".join(
        b.get("text", "") for b in payload.get("content", []) if isinstance(b, dict)
    )
    print("invoke_ok")
    print("class=ok")
    print("text_len", len(text))
except (ClientError, BotoCoreError, OSError) as e:
    msg = str(e)
    low = msg.lower()
    if "operation not allowed" in low:
        kind = "account_restriction"
    elif "accessdenied" in low or "not authorized to perform" in low:
        kind = "iam_denied"
    elif "resourcenotfound" in low:
        kind = "model_not_found"
    else:
        kind = "request_failed"
    print("invoke_failed")
    print(f"class={kind}")
    print(msg[:400])
    raise SystemExit(2)
PY
status=$?

echo ""
if [[ "$status" -eq 0 ]]; then
  echo "PASS: Bedrock invoke works in $REGION."
  exit 0
fi
echo "See docs/aws/BEDROCK_ACCOUNT_RESTRICTION.md"
echo "account_restriction → AWS Support (cannot be fixed in this repo)."
echo "iam_denied → instance role / IAM policy."
echo "model_not_found → enable the model in Bedrock console for $REGION."
exit "$status"
