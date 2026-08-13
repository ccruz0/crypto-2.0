# IAM hygiene after the leaked ROOT access key

PROD already assumes `atp-backend-ec2-role` (PR #463). This runbook is **read-only
unless you explicitly deactivate a leftover IAM user key**. Do not create a new
access key.

## 1. Confirm ROOT has no keys (console)

IAM API cannot list ROOT keys. Sign in as root (or the account owner) and open:

https://console.aws.amazon.com/iam/home#/security_credentials

Confirm **Access keys = none**. If a key still exists, delete it. Do not create a replacement.

## 2. List IAM user keys (Mac, SSO)

```bash
aws sso login --profile carlos-sso
AWS_PROFILE=carlos-sso ./scripts/aws/audit_iam_access_keys.sh
```

The script prints each IAM user's access-key ID, status, create date, and last used
service. It does not print secrets and does not change anything.

## 3. What to leave alone until the matching PR lands

| Principal | Why |
|-----------|-----|
| `jarvis-lab-bedrock` IAM user | LAB Bedrock static user. Deactivate its keys only after the LAB instance-role cutover. |
| GitHub Actions `AWS_ACCESS_KEY_ID` secret | Workflows still using static keys. Remove the **repo secret** only after those workflows use OIDC (`AWS_DEPLOY_ROLE_ARN`). |

## 4. What to deactivate if the audit shows it

Any **other** IAM user access key that:

- you do not recognize, or
- has not been used, or
- was created around the leak window

Deactivate first (`Inactive`); delete after a few days if nothing breaks.

```bash
# example only — fill in from the audit output
AWS_PROFILE=carlos-sso aws iam update-access-key \
  --user-name '<iam-user>' \
  --access-key-id 'AKIA...' \
  --status Inactive
```

Do not put that access-key ID in git.

## 5. CloudTrail (optional)

In the console, filter CloudTrail for `EventName = CreateAccessKey` and
`EventName = AssumeRole` around the leak dates. Confirm no new long-lived keys
were created after the ROOT key was deleted (9 Aug 2026).
