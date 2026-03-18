## Task

HARD RESET: purchase_price investigation  (Notion: `inv-task-456`)

## Repo

(see affected files)

## Root cause

Sync issue in get_purchase_price.

## Affected files

- `backend/app/services/foo.py`

## Constraints

- Build on the current implementation
- Change only the parts needed
- Keep the rest untouched
- Do not refactor unrelated code
- Preserve existing architecture unless explicitly required

## Expected outcome

Add fallback to exchange API.

## Testing requirements

- Verify the fix resolves the reported issue
- Run existing tests / linter to confirm no regressions
- Manual smoke-test if automated coverage is insufficient
