#!/usr/bin/env python3
"""Ready draft PRs to main, enable squash auto-merge, and merge when green.

Cloud agents open PRs as drafts; the previous workflow skipped those, so
auto-merge never armed. Bugbot inline threads also keep mergeStateStatus
BLOCKED while protect-main-production requires conversation resolution.

This script:
1. Marks the PR ready for review if it is still a draft.
2. Enables GitHub squash auto-merge (GitHub merges later if we cannot now).
3. Resolves leftover bot-only review threads after Cursor Bugbot approves.
4. Squash-merges immediately when mergeStateStatus is CLEAN/UNSTABLE.

Does not resolve threads that include a human reviewer, and does not merge
when reviewDecision is CHANGES_REQUESTED.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

BOT_LOGINS = frozenset(
    {
        "cursor",
        "cursor[bot]",
        "app/cursor",
        "github-actions[bot]",
        "copilot",
        "copilot[bot]",
        "copilot-pull-request-reviewer[bot]",
    }
)

IMMEDIATE_MERGE_STATUSES = frozenset({"CLEAN", "UNSTABLE", "HAS_HOOKS"})
TERMINAL_PR_STATES = frozenset({"MERGED", "CLOSED"})
POLL_SECONDS_DEFAULT = 90
POLL_INTERVAL_SECONDS = 5


class GhError(RuntimeError):
    """gh CLI returned a non-zero exit code."""


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GH_PAGER", "cat")
    env.setdefault("NO_COLOR", "1")
    result = subprocess.run(
        ["gh", *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GhError(f"gh {' '.join(args)} failed ({result.returncode}): {detail}")
    return result


def is_bot_login(login: str | None) -> bool:
    if not login:
        return False
    return login.lower() in {item.lower() for item in BOT_LOGINS}


def is_bot_only_thread(thread: dict[str, Any]) -> bool:
    comments = thread.get("comments", {}).get("nodes") or []
    logins = [((node.get("author") or {}).get("login") or "") for node in comments]
    if not logins:
        return False
    return all(is_bot_login(login) for login in logins)


def can_immediate_merge(merge_state_status: str | None) -> bool:
    return (merge_state_status or "").upper() in IMMEDIATE_MERGE_STATUSES


def should_skip_pr(state: str | None, merged: bool) -> bool:
    if merged:
        return True
    return (state or "").upper() in TERMINAL_PR_STATES


def should_resolve_bot_threads(review_decision: str | None) -> bool:
    """Only clear leftover Bugbot threads after an explicit approve.

    An empty decision means Bugbot has not finished; resolving then would
    hide in-flight findings and merge before the review lands.
    """
    return (review_decision or "").upper() == "APPROVED"


def parse_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise ValueError(f"Invalid GITHUB_REPOSITORY: {repo!r}")
    return owner, name


def load_pr(number: int) -> dict[str, Any]:
    result = run_gh(
        [
            "pr",
            "view",
            str(number),
            "--json",
            "number,url,isDraft,state,mergedAt,mergeStateStatus,reviewDecision,autoMergeRequest",
        ]
    )
    return json.loads(result.stdout)


def list_unresolved_threads(owner: str, name: str, number: int) -> list[dict[str, Any]]:
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              comments(first: 20) {
                nodes { author { login } }
              }
            }
          }
        }
      }
    }
    """
    result = run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
    )
    payload = json.loads(result.stdout)
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes")
        or []
    )
    return [node for node in nodes if not node.get("isResolved")]


def resolve_thread(thread_id: str) -> None:
    mutation = """
    mutation($id: ID!) {
      resolveReviewThread(input: {threadId: $id}) {
        thread { isResolved }
      }
    }
    """
    run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={mutation}",
            "-F",
            f"id={thread_id}",
        ]
    )


def mark_ready(number: int) -> None:
    result = run_gh(["pr", "ready", str(number)], check=False)
    if result.returncode != 0:
        combined = f"{result.stdout} {result.stderr}".lower()
        if "not a draft" in combined or "already ready" in combined:
            return
        raise GhError(
            f"gh pr ready failed ({result.returncode}): {(result.stderr or result.stdout).strip()}"
        )


def auto_merge_enable_ok(returncode: int, output: str) -> bool:
    if returncode == 0:
        return True
    lowered = output.lower()
    return any(
        token in lowered
        for token in (
            "already merged",
            "already enabled",
            "not mergeable",
            "blocked by",
            "required status",
            "review thread",
            "pull request is in draft",
        )
    )


def enable_auto_merge(url: str) -> str:
    result = run_gh(["pr", "merge", url, "--auto", "--squash"], check=False)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if auto_merge_enable_ok(result.returncode, output):
        return output or "auto-merge enabled"
    raise GhError(f"Could not enable auto-merge: {output}")


def squash_merge_now(url: str) -> str:
    result = run_gh(["pr", "merge", url, "--squash"], check=False)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        return output.strip() or "squash-merged"
    lowered = output.lower()
    if "already merged" in lowered:
        return output.strip()
    raise GhError(f"Immediate squash merge failed: {output.strip()}")


def resolve_eligible_bot_threads(
    owner: str, name: str, number: int, review_decision: str | None
) -> int:
    if not should_resolve_bot_threads(review_decision):
        print(
            f"Skipping bot-thread resolution (reviewDecision={review_decision or 'none'})",
            flush=True,
        )
        return 0
    unresolved = list_unresolved_threads(owner, name, number)
    resolved = 0
    for thread in unresolved:
        if not is_bot_only_thread(thread):
            authors = [
                ((node.get("author") or {}).get("login") or "?")
                for node in (thread.get("comments", {}).get("nodes") or [])
            ]
            print(f"Leaving human review thread unresolved ({', '.join(authors)})", flush=True)
            continue
        resolve_thread(thread["id"])
        resolved += 1
        print(f"Resolved bot review thread {thread['id']}", flush=True)
    return resolved


def process_pr(
    number: int,
    repo: str,
    *,
    poll_seconds: int = POLL_SECONDS_DEFAULT,
    dry_run: bool = False,
) -> int:
    owner, name = parse_repo(repo)
    pr = load_pr(number)
    url = pr["url"]
    print(
        f"PR #{number} draft={pr.get('isDraft')} state={pr.get('state')} "
        f"mergeStateStatus={pr.get('mergeStateStatus')} "
        f"reviewDecision={pr.get('reviewDecision') or 'none'}",
        flush=True,
    )
    if should_skip_pr(pr.get("state"), bool(pr.get("mergedAt"))):
        print("PR already merged or closed; nothing to do.", flush=True)
        return 0

    if pr.get("isDraft"):
        print("PR is draft; marking ready for review so auto-merge can arm.", flush=True)
        if not dry_run:
            mark_ready(number)

    if not dry_run:
        resolve_eligible_bot_threads(owner, name, number, pr.get("reviewDecision"))
        message = enable_auto_merge(url)
        print(message, flush=True)
    else:
        print("dry-run: skip ready / resolve / auto-merge", flush=True)

    deadline = time.monotonic() + max(0, poll_seconds)
    last_status = pr.get("mergeStateStatus")
    while True:
        pr = load_pr(number)
        last_status = pr.get("mergeStateStatus")
        if should_skip_pr(pr.get("state"), bool(pr.get("mergedAt"))):
            print("PR merged or closed during wait.", flush=True)
            return 0
        if can_immediate_merge(last_status):
            print(f"mergeStateStatus={last_status}; squash-merging now.", flush=True)
            if dry_run:
                print("dry-run: skip squash merge", flush=True)
                return 0
            print(squash_merge_now(url), flush=True)
            return 0
        if last_status == "DIRTY":
            print("PR has conflicts; cannot auto-merge.", flush=True)
            return 1
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    print(
        f"Auto-merge armed; waiting on GitHub (mergeStateStatus={last_status}, "
        f"reviewDecision={pr.get('reviewDecision') or 'none'}). "
        "A later Path Guard / Bugbot event will retry.",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in args
    args = [item for item in args if item != "--dry-run"]
    number_raw = args[0] if args else os.environ.get("PR_NUMBER") or os.environ.get(
        "GITHUB_PR_NUMBER"
    )
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    poll_raw = os.environ.get("AUTO_MERGE_POLL_SECONDS", str(POLL_SECONDS_DEFAULT))
    if not number_raw:
        print("PR_NUMBER is required", file=sys.stderr)
        return 2
    if not repo:
        print("GITHUB_REPOSITORY is required", file=sys.stderr)
        return 2
    return process_pr(
        int(number_raw),
        repo,
        poll_seconds=int(poll_raw),
        dry_run=dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
