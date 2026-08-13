# Bedrock `"Operation not allowed"` — account restriction

Jarvis uses Amazon Bedrock (`backend/app/jarvis/bedrock_client.py`). After the
prod instance-role cutover (#463), IAM is no longer the blocker when the error
is **`Operation not allowed`**. That string is an **AWS account restriction**.
No IAM policy, instance role, or access key will lift it.

## 1. Classify (Mac)

```bash
aws sso login --profile carlos-sso
AWS_PROFILE=carlos-sso JARVIS_BEDROCK_REGION=us-east-1 \
  ./scripts/aws/probe_bedrock_account_status.sh
```

| `class=` | Meaning | What to do |
|----------|---------|------------|
| `ok` | Invoke succeeded | Nothing. Jarvis can call Bedrock. |
| `account_restriction` | `Operation not allowed` | Open AWS Support. Code/IAM will not fix this. |
| `iam_denied` | `AccessDeniedException` | Fix instance role / GHA OIDC policy. |
| `model_not_found` | Model ID not enabled in that region | Bedrock console → Model access. |

Logs from `ask_bedrock` now include the same class, e.g.
`Bedrock request failed (account_restriction): ...`.

## 2. AWS Support (only for `account_restriction`)

In the AWS console (account `634531197711`):

1. Support → Create case → **Account and billing** or **Service limit increase**
   for Amazon Bedrock (whichever the current console offers for model access).
2. State: Bedrock `InvokeModel` returns **Operation not allowed** for Claude
   on `us-east-1` / `ap-southeast-1` from instance role `atp-backend-ec2-role`
   (and LAB `atp-lab-ec2-role` once attached).
3. Ask AWS to enable Anthropic Claude on Bedrock for this account.
4. Do **not** create a new access key as a workaround.

Until AWS lifts it, Jarvis planner/LLM paths return empty and fall back to
non-Bedrock logic. Trading does not depend on Bedrock.

## 3. What we already ruled out

- Missing static `AWS_ACCESS_KEY_ID` on prod — intended; prod uses the instance role.
- Revoked ROOT key — that key must stay deleted.
- Wrong region/model — still possible (`model_not_found`); probe both
  `us-east-1` and `ap-southeast-1` if needed.
