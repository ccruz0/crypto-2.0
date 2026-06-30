# CI/CD frontend — operator setup (run with AWS admin)

Run these **yourself** with admin credentials. Cursor must NOT execute IAM/OIDC/ECR
changes (the production host's instance profile `EC2_SSM_Role` is denied IAM/ECR
admin by design). Nothing here touches the trading backend.

Fixed values (discovered, read-only):

- Account: `634531197711`
- Region: `ap-southeast-1`
- PROD instance (dashboard): `i-087953603011543c5` (`atp-rebuild-2026`)
- Repo: `ccruz0/crypto-2.0`
- ECR repo to create: `atp-frontend`
- Instance profile role used by PROD: `EC2_SSM_Role`

All policy JSONs referenced below live in `ci-cd/iam/`.

---

## 0. Pre-checks (read-only)

```bash
export AWS_REGION=ap-southeast-1
aws sts get-caller-identity
aws ecr describe-repositories --region "$AWS_REGION" --query "repositories[].repositoryName" --output text 2>/dev/null || echo "none / no access"
aws iam list-open-id-connect-providers
```

## 1. ECR repository (create if missing)

```bash
aws ecr describe-repositories --repository-names atp-frontend --region "$AWS_REGION" \
  || aws ecr create-repository \
       --repository-name atp-frontend \
       --image-scanning-configuration scanOnPush=true \
       --image-tag-mutability MUTABLE \
       --region "$AWS_REGION"
```

Note the `repositoryUri` → it is `634531197711.dkr.ecr.ap-southeast-1.amazonaws.com/atp-frontend`.

## 2. GitHub OIDC provider (create if missing)

```bash
# Skip if it already exists (see pre-checks).
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
# (IAM validates GitHub's OIDC against a managed CA set; the thumbprint is still
#  required by the API. Verify the current value if AWS rejects it.)
```

Resulting ARN: `arn:aws:iam::634531197711:oidc-provider/token.actions.githubusercontent.com`

## 3. Deploy role `gha-deploy-frontend`

```bash
aws iam create-role \
  --role-name gha-deploy-frontend \
  --assume-role-policy-document file://ci-cd/iam/trust-gha-deploy-frontend.json \
  --description "GitHub Actions OIDC role: build->ECR push->SSM deploy frontend-aws only"

aws iam put-role-policy \
  --role-name gha-deploy-frontend \
  --policy-name gha-deploy-frontend-perms \
  --policy-document file://ci-cd/iam/policy-gha-deploy-frontend.json
```

Role ARN (for the GitHub secret): `arn:aws:iam::634531197711:role/gha-deploy-frontend`

## 4. Allow the PROD host to PULL the frontend image (EC2_SSM_Role)

Least-privilege ECR **pull** only, scoped to `atp-frontend`:

```bash
aws iam put-role-policy \
  --role-name EC2_SSM_Role \
  --policy-name ecr-pull-atp-frontend \
  --policy-document file://ci-cd/iam/policy-ec2ssmrole-ecr-pull.json
```

## 5. GitHub repo configuration

Settings → Secrets and variables → Actions.

Variables:

| Name | Value |
|---|---|
| `AWS_REGION` | `ap-southeast-1` |
| `ECR_REPOSITORY` | `atp-frontend` |
| `EC2_INSTANCE_ID` | `i-087953603011543c5` |
| `COMPOSE_DIR` | `/home/ubuntu/crypto-2.0` |
| `COMPOSE_SERVICE` | `frontend-aws` |

Secret:

| Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::634531197711:role/gha-deploy-frontend` |

## 6. Safe test (Tarea 6)

The trust policy only allows `ref:refs/heads/main`. A `workflow_dispatch` from the
PR branch would present `sub = repo:ccruz0/crypto-2.0:ref:refs/heads/ci/deploy-frontend-ecr`
and **fail the AWS OIDC trust** (this is the intended least-privilege behavior).

Two ways to validate:

- **Recommended:** merge the PR, then run the workflow via `workflow_dispatch` on
  `main` (it will not change app code; it rebuilds+redeploys the current frontend).
- **Pre-merge (optional, temporary):** add a second `sub` to the trust to permit the
  test branch, then remove it after validating:

  ```bash
  # temporary: allow the test branch too (StringLike with both refs), revert after.
  # Edit trust-gha-deploy-frontend.json sub -> use "ForAnyValue:StringLike" with:
  #   "repo:ccruz0/crypto-2.0:ref:refs/heads/main"
  #   "repo:ccruz0/crypto-2.0:ref:refs/heads/ci/deploy-frontend-ecr"
  aws iam update-assume-role-policy --role-name gha-deploy-frontend \
    --policy-document file://ci-cd/iam/trust-gha-deploy-frontend.json
  ```

Verify after a run:
- `aws ecr list-images --repository-name atp-frontend --region ap-southeast-1`
- SSM command status = `Success`
- Health: `/` and `/peluqueria` return 2xx/3xx (the workflow rolls back on failure).
