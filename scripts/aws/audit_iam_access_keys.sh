#!/usr/bin/env bash
# Read-only IAM hygiene after the leaked ROOT access key.
# Lists IAM user access keys (status, created, last used). Does not create,
# delete, or deactivate keys. Cannot list ROOT keys via the IAM API.
#
# Run from the operator Mac:
#   AWS_PROFILE=carlos-sso ./scripts/aws/audit_iam_access_keys.sh
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"

echo "=== IAM access-key audit (read-only) ==="
echo "Profile: $AWS_PROFILE  Region: $REGION"
echo ""

if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"
echo "Account: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Account'])" "$ID_JSON")"
echo ""

echo "=== ROOT access keys (console only) ==="
echo "IAM Identity Center / IAM users cannot list ROOT keys."
echo "Open: https://console.aws.amazon.com/iam/home#/security_credentials"
echo "Confirm: Access keys = none. Do not create a replacement key."
echo ""

echo "=== IAM users with access keys ==="
python3 - <<'PY'
import json, subprocess, sys

def aws(*args):
    p = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr or "aws failed\n")
        sys.exit(1)
    return json.loads(p.stdout) if p.stdout.strip() else {}

users = aws("iam", "list-users").get("Users") or []
if not users:
    print("(no IAM users)")
    raise SystemExit(0)

rows = []
for u in users:
    name = u["UserName"]
    keys = aws("iam", "list-access-keys", "--user-name", name).get("AccessKeyMetadata") or []
    if not keys:
        rows.append((name, "-", "-", "-", "-", "no keys"))
        continue
    for k in keys:
        kid = k.get("AccessKeyId") or ""
        status = k.get("Status") or ""
        created = (k.get("CreateDate") or "")[:10]
        last = "never"
        last_svc = "-"
        try:
            lu = aws("iam", "get-access-key-last-used", "--access-key-id", kid)
            info = (lu.get("AccessKeyLastUsed") or {})
            last = str(info.get("LastUsedDate") or "never")[:10]
            last_svc = info.get("ServiceName") or "-"
        except SystemExit:
            raise
        except Exception:
            last = "?"
        note = ""
        if name == "jarvis-lab-bedrock":
            note = "LAB user — deactivate keys only after instance-role cutover"
        rows.append((name, kid, status, created, f"{last}/{last_svc}", note))

print(f"{'user':<28} {'key_id':<24} {'status':<10} {'created':<12} {'last_used/svc':<22} note")
for r in rows:
    print(f"{r[0]:<28} {r[1]:<24} {r[2]:<10} {r[3]:<12} {r[4]:<22} {r[5]}")
PY

echo ""
echo "=== ATP-related instance profiles / roles (names only) ==="
aws iam list-instance-profiles --query 'InstanceProfiles[].{Name:InstanceProfileName,Roles:Roles[].RoleName}' --output table
echo ""
echo "PASS: audit complete. No keys were changed."
echo "Next: if any IAM user still has Active keys you do not recognize, deactivate in the console"
echo "AFTER confirming they are not GitHub Actions (migrate those to OIDC) or LAB jarvis-lab-bedrock."
