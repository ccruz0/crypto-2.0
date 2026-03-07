# Agent Versioning Flow

This workflow adds explicit business-logic version traceability across:

- Notion task metadata
- Telegram approval actions
- Agent activity log events
- `docs/releases/CHANGELOG.md`

## Required version metadata

Primary fields:

- `current_version`
- `proposed_version`
- `released_version`
- `version_status` (`proposed`, `approved`, `released`, `rejected`)
- `change_summary`

Recommended additional field:

- `approved_version`

## Proposal stage

When a task is prepared for execution, version metadata is proposed and attached to the prepared bundle:

- `proposed_version`
- `change_summary`
- `affected_files`
- `validation_plan`

The proposal is then written to Notion (best effort) if those Notion properties exist.
If the Notion DB does not yet contain these properties, updates are skipped safely and execution continues.

## Approval stage

Telegram approval records whether the proposed version is accepted:

- Approve -> `version_status=approved` and `approved_version=proposed_version` (best effort in Notion)
- Deny -> `version_status=rejected` (best effort in Notion)

## Release stage

After successful execution (apply + validation + status moved to deployed):

- `released_version` is recorded
- `version_status` becomes `released`
- A Notion release comment is appended
- Activity event `version_released` is logged
- A release entry is appended to `docs/releases/CHANGELOG.md`

## Versioning rules

- `patch`: small tuning changes
- `minor`: meaningful business-logic improvements
- `major`: architecture or core-strategy changes

## Traceability map

- Notion page: source task and mutable version metadata
- Telegram: human approval/denial action
- `logs/agent_activity.jsonl`: immutable workflow events (`version_proposed`, `version_released`)
- `docs/releases/CHANGELOG.md`: release-oriented historical record
