# Git Branching & Release Strategy

This document describes the recommended Git workflow for this project.

## Branch Strategy

### Main Branches

- **`main`**: Production-ready code
  - Protected branch (requires PR review)
  - Auto-deploys to AWS production via GitHub Actions
  - Only merge after testing in staging/local

- **`develop`** (optional): Integration branch for features
  - If using this, merge features here first
  - Then merge to `main` when ready for production

### Feature Branches

- **Naming**: `feature/description` or `fix/description`
- **Examples**:
  - `feature/add-telegram-commands`
  - `fix/backend-health-check`
  - `fix/frontend-css-issue`

### Release Branches (Optional)

- **Naming**: `release/v1.2.3`
- Use for preparing releases
- Merge to `main` when ready

## Recommended Workflow

### Simple Workflow (Recommended)

```
feature/fix-bug
    │
    ├─ Develop locally (see DEV.md)
    ├─ Test locally
    ├─ Create PR to main
    │
main ────┘
    │
    ├─ Auto-deploy to AWS (via GitHub Actions)
    └─ Verify in production
```

### Detailed Workflow

1. **Create feature branch:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/your-feature-name
   ```

2. **Develop and test locally:**
   ```bash
   # Make changes
   # Test locally (see DEV.md)
   docker compose --profile local up -d
   # Verify changes work
   ```

3. **Commit changes:**
   ```bash
   git add .
   git commit -m "feat: add feature description"
   # Use conventional commits:
   # feat: new feature
   # fix: bug fix
   # docs: documentation
   # refactor: code refactoring
   # test: tests
   # chore: maintenance
   ```

4. **Push and create PR:**
   ```bash
   git push origin feature/your-feature-name
   # Create PR on GitHub to main branch
   ```

5. **Code review:**
   - Reviewer checks code
   - Address review comments
   - Update PR if needed

6. **Merge to main:**
   - Merge PR (squash or merge commit)
   - GitHub Actions automatically deploys to AWS

7. **Verify deployment:**
   - Check GitHub Actions workflow
   - Verify services on AWS
   - Monitor logs

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
type(scope): subject

body (optional)

footer (optional)
```

**Examples:**
```
feat(backend): add new trading endpoint
fix(frontend): correct dashboard refresh issue
docs: update deployment instructions
refactor(backend): simplify order processing logic
test(backend): add tests for signal monitor
chore: update dependencies
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `style`: Formatting (no code change)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

## Release Strategy

### Versioning

Use [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Creating a Release

1. **Update version** (if tracked in code):
   ```bash
   # Update version in package.json, version file, etc.
   git commit -m "chore: bump version to 1.2.3"
   ```

2. **Create git tag:**
   ```bash
   git tag -a v1.2.3 -m "Release version 1.2.3"
   git push origin v1.2.3
   ```

3. **Deploy:**
   - Merge to `main` (if not already)
   - GitHub Actions deploys automatically
   - Or deploy manually (see DEPLOY.md)

4. **Create GitHub Release** (optional):
   - Go to GitHub → Releases → New release
   - Select tag
   - Add release notes
   - Publish

## Hotfix Workflow

For urgent production fixes:

1. **Create hotfix branch from main:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b hotfix/critical-fix
   ```

2. **Fix and test:**
   ```bash
   # Make minimal fix
   # Test locally if possible
   ```

3. **Deploy quickly:**
   ```bash
   git commit -m "fix: critical production fix"
   git push origin hotfix/critical-fix
   # Create PR and merge immediately (or merge directly if urgent)
   ```

4. **Backport to develop** (if using develop branch):
   ```bash
   git checkout develop
   git cherry-pick hotfix-commit-hash
   git push origin develop
   ```

## Best Practices

1. **Keep branches short-lived:**
   - Merge feature branches within days/weeks
   - Avoid long-running feature branches

2. **Test before merging:**
   - Test locally (see DEV.md)
   - Run tests if available
   - Verify deployment works

3. **Small, focused commits:**
   - One logical change per commit
   - Easier to review and revert if needed

4. **Write clear commit messages:**
   - Explain what and why, not how
   - Reference issues if applicable

5. **Review before merging:**
   - Use PRs for code review
   - Get approval before merging to main

6. **Don't force push to main:**
   - Protect main branch
   - Use PRs and merges

## GitHub Actions Integration

The project uses GitHub Actions for automated deployment:

- **Trigger**: Push to `main` branch
- **Workflow**: `.github/workflows/deploy_session_manager.yml`
- **Action**: Deploys to AWS EC2 via SSM Session Manager

**To disable auto-deploy temporarily:**
- Comment out workflow file
- Or use `[skip ci]` in commit message (if configured)

## Example Workflow

```bash
# 1. Start new feature
git checkout main
git pull origin main
git checkout -b feature/add-new-endpoint

# 2. Develop locally
# ... make changes ...
docker compose --profile local up -d
# ... test changes ...

# 3. Commit and push
git add .
git commit -m "feat(backend): add new trading endpoint"
git push origin feature/add-new-endpoint

# 4. Create PR on GitHub
# ... wait for review ...

# 5. Merge PR
# ... GitHub Actions deploys automatically ...

# 6. Verify deployment
ssh ubuntu@AWS_IP
docker compose --profile aws ps
curl http://localhost:8002/ping_fast
```

## Troubleshooting

### Merge Conflicts

```bash
# Pull latest main
git checkout main
git pull origin main

# Rebase feature branch
git checkout feature/your-feature
git rebase main
# Resolve conflicts
git add .
git rebase --continue

# Force push (if already pushed)
git push origin feature/your-feature --force-with-lease
```

### Undo Last Commit

```bash
# Undo commit, keep changes
git reset --soft HEAD~1

# Undo commit, discard changes (⚠️ destructive)
git reset --hard HEAD~1
```

### Sync Fork (if using forks)

```bash
git remote add upstream <original-repo-url>
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

## Next Steps

- See [DEV.md](./DEV.md) for local development
- See [DEPLOY.md](./DEPLOY.md) for deployment procedures



