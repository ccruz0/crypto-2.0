## Task

E2E test bug  (Notion: `e2e-test-001`)

## Repo

General

## Root cause

Off by one

## Affected files

- (none identified — locate the relevant files before patching)

## Constraints

- Build on the current implementation
- Change only the parts needed
- Keep the rest untouched
- Do not refactor unrelated code
- Preserve existing architecture unless explicitly required

## Expected outcome

Found the bug

## Testing requirements

- Verify the fix resolves the reported issue
- Run existing tests / linter to confirm no regressions
- Manual smoke-test if automated coverage is insufficient
