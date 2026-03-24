"""Durable autonomous runner launcher (MVP v7)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {"starting", "running", "deploy_requested", "deploying"}
_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "blocked",
    "release_candidate_ready",
    "rejected",
    "deployed",
    "deploy_failed",
    "post_deploy_failed",
}
_STALE_SECONDS = int((os.environ.get("AUTONOMOUS_RUNNER_STALE_SECONDS") or "").strip() or 1800)
_MAX_HISTORY_PER_DEDUP_KEY = 5
_POST_DEPLOY_HEALTH_URL_DEFAULT = "http://127.0.0.1:8000/api/ping_fast"
_POST_DEPLOY_HEALTH_EXPECT_DEFAULT = '"status":"ok"'
_STATUS_MAP_BY_EVENT = {
    "investigation_started": "investigating",
    "cursor_started": "patching",
    "execution_started": "testing",
    "review_started": "verifying",
}


def launch_autonomous_runner(
    *,
    project: str,
    repo_path: str,
    title: str,
    details: str,
    env: str = "prod",
    max_iterations: int = 3,
    notion_page_id: str = "",
    telegram_chat_hint: str = "",
) -> dict[str, Any]:
    """Start runner through durable detached worker process."""
    rp = Path(repo_path).resolve()
    if not rp.exists():
        return {"accepted": False, "task_id": "", "run_dir": "", "status": "rejected", "error": f"repo_path not found: {rp}"}

    now = time.time()
    dedup_key = (notion_page_id or "").strip() or f"{project.strip().lower()}::{title.strip().lower()}"
    launch_id = f"arl-{uuid.uuid4().hex[:12]}"

    state = _read_state(rp)
    state = _reconcile_state(rp, state, now=now)
    _write_state(rp, state)
    existing = _find_active_run(state, dedup_key, now)
    if existing:
        return {
            "accepted": False,
            "task_id": str(existing.get("runner_task_id") or ""),
            "run_dir": str(existing.get("run_dir") or ""),
            "status": "already_running",
            "error": "",
        }

    rec = {
        "launch_id": launch_id,
        "dedup_key": dedup_key,
        "notion_page_id": (notion_page_id or "").strip(),
        "project": project,
        "title": title,
        "details": details,
        "env": env,
        "max_iterations": int(max_iterations),
        "status": "starting",
        "runner_task_id": "",
        "run_dir": "",
        "started_at": now,
        "finished_at": 0,
        "telegram_chat_hint": (telegram_chat_hint or "").strip(),
        "error": "",
    }
    state.setdefault("runs", []).append(rec)
    _compact_state(state)
    _write_state(rp, state)
    _mark_notion_created((notion_page_id or "").strip(), project, title)

    worker_payload = {"launch_id": launch_id, "repo_path": str(rp)}
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker-payload", json.dumps(worker_payload)]
    env_vars = os.environ.copy()
    backend_path = str(rp / "backend")
    py_path = env_vars.get("PYTHONPATH", "").strip()
    env_vars["PYTHONPATH"] = backend_path if not py_path else f"{backend_path}:{py_path}"
    try:
        subprocess.Popen(
            cmd,
            cwd=str(rp),
            env=env_vars,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        _update_launch_record(rp, launch_id, status="failed", error=f"worker start failed: {exc}", finished=True)
        _mark_notion_blocked((notion_page_id or "").strip(), f"worker start failed: {exc}")
        return {"accepted": False, "task_id": "", "run_dir": "", "status": "failed", "error": str(exc)}

    return {"accepted": True, "task_id": "", "run_dir": "", "status": "starting", "error": ""}


def _worker_main(worker_payload: dict[str, Any]) -> int:
    repo_path = Path(str(worker_payload.get("repo_path") or ".")).resolve()
    launch_id = str(worker_payload.get("launch_id") or "").strip()
    state = _read_state(repo_path)
    rec = _get_record(state, launch_id)
    if not rec:
        return 1

    project = str(rec.get("project") or "").strip() or "ATP"
    title = str(rec.get("title") or "").strip()
    details = str(rec.get("details") or "").strip()
    env_name = str(rec.get("env") or "prod").strip()
    max_iterations = int(rec.get("max_iterations") or 3)
    notion_page_id = str(rec.get("notion_page_id") or "").strip()

    _notify_ops("runner started", project, title, task_id="", run_dir="", status="starting")
    _update_launch_record(repo_path, launch_id, status="running")

    cmd = [
        sys.executable,
        "tools/autonomous_runner.py",
        "--project",
        project,
        "--title",
        title,
        "--details",
        details,
        "--env",
        env_name,
        "--max-iterations",
        str(max_iterations),
    ]
    env_vars = os.environ.copy()
    backend_path = str(repo_path / "backend")
    py_path = env_vars.get("PYTHONPATH", "").strip()
    env_vars["PYTHONPATH"] = backend_path if not py_path else f"{backend_path}:{py_path}"

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_path),
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        _update_launch_record(repo_path, launch_id, status="failed", error=f"runner start failed: {exc}", finished=True)
        _mark_notion_blocked(notion_page_id, f"runner start failed: {exc}")
        _notify_ops("runner blocked", project, title, task_id="", run_dir="", status="failed")
        return 1

    run_dir = ""
    task_id = ""
    emitted_events: set[str] = set()
    timeline_idx = 0
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            txt = line.strip()
            if txt.startswith("Run dir:"):
                run_dir = txt.split("Run dir:", 1)[1].strip()
                task_id = Path(run_dir).name if run_dir else ""
                _update_launch_record(repo_path, launch_id, runner_task_id=task_id, run_dir=run_dir, status="running")
                _link_notion_runner(notion_page_id, task_id, run_dir)
                _notify_ops("runner started", project, title, task_id=task_id, run_dir=run_dir, status="running")
        if run_dir:
            timeline_idx = _consume_timeline_events(
                run_dir=run_dir,
                notion_page_id=notion_page_id,
                emitted_events=emitted_events,
                timeline_idx=timeline_idx,
            )
        if proc.poll() is not None:
            break
        time.sleep(0.2)

    final_summary = _read_final_summary(run_dir)
    final_status = str(final_summary.get("status") or ("ok" if int(proc.returncode or 0) == 0 else "blocked"))
    if final_status == "ok":
        rc = _write_release_candidate_artifact(
            run_dir=run_dir,
            task_id=task_id,
            project=project,
            title=title,
            final_summary=final_summary,
        )
        _update_launch_record(
            repo_path,
            launch_id,
            status="release_candidate_ready",
            error="",
            finished=True,
        )
        _mark_notion_release_candidate_ready(notion_page_id, rc, task_id, run_dir)
        _notify_release_candidate_ready(
            project,
            title,
            task_id=task_id,
            run_dir=run_dir,
            rc=rc,
            launch_id=launch_id,
        )
    elif final_status == "blocked":
        _update_launch_record(repo_path, launch_id, status="blocked", error=str(final_summary.get("blocking_reason") or ""), finished=True)
        _mark_notion_blocked(notion_page_id, str(final_summary.get("blocking_reason") or "blocked"))
        _notify_ops("runner blocked", project, title, task_id=task_id, run_dir=run_dir, status="blocked")
    else:
        _update_launch_record(repo_path, launch_id, status="failed", error=str(final_summary.get("blocking_reason") or final_status), finished=True)
        _mark_notion_blocked(notion_page_id, str(final_summary.get("blocking_reason") or final_status))
        _notify_ops("runner blocked", project, title, task_id=task_id, run_dir=run_dir, status="failed")
    return 0


def _state_path(repo_path: Path) -> Path:
    p = _runtime_agent_runs_dir(repo_path) / "launcher_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _runtime_agent_runs_dir(repo_path: Path) -> Path:
    """
    Resolve writable runtime/agent_runs directory for launcher state.
    Priority:
      1) AUTONOMOUS_RUNTIME_DIR (if set)
      2) <repo_path>/runtime/agent_runs
      3) /app/runtime/agent_runs
      4) /tmp/runtime/agent_runs
    """
    env_root = (os.environ.get("AUTONOMOUS_RUNTIME_DIR") or "").strip()
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve() / "agent_runs")
    candidates.extend(
        [
            repo_path / "runtime" / "agent_runs",
            Path("/app/runtime/agent_runs"),
            Path("/tmp/runtime/agent_runs"),
        ]
    )
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise OSError("No writable runtime directory available for autonomous runner launcher")


@contextmanager
def _state_lock(repo_path: Path):
    lock_path = _state_path(repo_path).with_suffix(".lock")
    fd = open(lock_path, "a+", encoding="utf-8")
    try:
        import fcntl
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fd.close()


def _read_state(repo_path: Path) -> dict[str, Any]:
    p = _state_path(repo_path)
    with _state_lock(repo_path):
        if not p.exists():
            return {"runs": []}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"runs": []}
        except Exception:
            return {"runs": []}


def _write_state(repo_path: Path, state: dict[str, Any]) -> None:
    p = _state_path(repo_path)
    tmp = p.with_suffix(".tmp")
    with _state_lock(repo_path):
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, p)


def _reconcile_state(repo_path: Path, state: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """
    Reconcile starting/running records using run_dir/final_summary and stale threshold.
    """
    tnow = now if now is not None else time.time()
    runs = state.get("runs")
    if not isinstance(runs, list):
        state["runs"] = []
        return state
    for rec in runs:
        if not isinstance(rec, dict):
            continue
        st = str(rec.get("status") or "")
        if st not in _ACTIVE_STATUSES:
            continue
        run_dir = str(rec.get("run_dir") or "").strip()
        if run_dir:
            final = _read_final_summary(run_dir)
            if final:
                fstatus = str(final.get("status") or "").strip().lower()
                if fstatus == "ok":
                    rec["status"] = "completed"
                    rec["error"] = ""
                elif fstatus == "blocked":
                    rec["status"] = "blocked"
                    rec["error"] = str(final.get("blocking_reason") or "blocked")
                else:
                    rec["status"] = "failed"
                    rec["error"] = str(final.get("blocking_reason") or fstatus or "failed")
                rec["finished_at"] = float(rec.get("finished_at") or 0) or tnow
                continue
        started_at = float(rec.get("started_at") or 0)
        if started_at and (tnow - started_at) > _STALE_SECONDS:
            rec["status"] = "failed"
            rec["error"] = f"stale_run_timeout>{_STALE_SECONDS}s"
            rec["finished_at"] = float(rec.get("finished_at") or 0) or tnow
    _compact_state(state)
    return state


def _compact_state(state: dict[str, Any]) -> None:
    """
    Keep latest records and cap history per dedup_key.
    """
    runs = state.get("runs")
    if not isinstance(runs, list):
        state["runs"] = []
        return
    valid = [r for r in runs if isinstance(r, dict)]
    valid.sort(key=lambda r: float(r.get("started_at") or 0))
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in valid:
        key = str(r.get("dedup_key") or "")
        by_key.setdefault(key, []).append(r)
    kept: list[dict[str, Any]] = []
    for _, lst in by_key.items():
        active = [r for r in lst if str(r.get("status") or "") in _ACTIVE_STATUSES]
        terminals = [r for r in lst if str(r.get("status") or "") in _TERMINAL_STATUSES]
        tail_terminals = terminals[-_MAX_HISTORY_PER_DEDUP_KEY:]
        # Keep all active + bounded terminal history.
        kept.extend(active + tail_terminals)
    kept.sort(key=lambda r: float(r.get("started_at") or 0))
    # Global cap as final safety.
    state["runs"] = kept[-500:]


def _find_active_run(state: dict[str, Any], dedup_key: str, now: float) -> dict[str, Any] | None:
    for r in reversed(state.get("runs") or []):
        if str(r.get("dedup_key") or "") != dedup_key:
            continue
        status = str(r.get("status") or "")
        started_at = float(r.get("started_at") or 0)
        finished_at = float(r.get("finished_at") or 0)
        if status in _ACTIVE_STATUSES:
            return r
        if not finished_at and started_at and (now - started_at) < 3600:
            return r
    return None


def _get_record(state: dict[str, Any], launch_id: str) -> dict[str, Any] | None:
    for r in state.get("runs") or []:
        if str(r.get("launch_id") or "") == launch_id:
            return r
    return None


def _update_launch_record(repo_path: Path, launch_id: str, **updates: Any) -> None:
    state = _read_state(repo_path)
    rec = _get_record(state, launch_id)
    if not rec:
        return
    rec.update({k: v for k, v in updates.items() if v is not None})
    if updates.get("finished"):
        rec["finished_at"] = time.time()
    _write_state(repo_path, state)
    if rec.get("notion_page_id"):
        _safe_update_metadata(
            str(rec.get("notion_page_id")),
            {
                "final_result": (
                    f"launch_status={rec.get('status')} "
                    f"runner_task_id={rec.get('runner_task_id') or '-'} "
                    f"run_dir={rec.get('run_dir') or '-'}"
                )
            },
            append_comment=f"Launcher status -> {rec.get('status')}",
        )


def _consume_timeline_events(
    *,
    run_dir: str,
    notion_page_id: str,
    emitted_events: set[str],
    timeline_idx: int,
) -> int:
    path = Path(run_dir) / "timeline.log"
    if not path.exists():
        return timeline_idx
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return timeline_idx
    for i in range(timeline_idx, len(lines)):
        parts = [p.strip() for p in lines[i].split("|")]
        if len(parts) < 3:
            continue
        event = parts[1]
        if event in emitted_events:
            continue
        emitted_events.add(event)
        mapped = _STATUS_MAP_BY_EVENT.get(event)
        if mapped:
            _safe_update_status(notion_page_id, mapped, append_comment=f"Runner event: {event}")
        if event == "blocked":
            _safe_update_status(notion_page_id, "blocked", append_comment=f"Runner event: {event}")
    return len(lines)


def _read_final_summary(run_dir: str) -> dict[str, Any]:
    if not run_dir:
        return {}
    p = Path(run_dir) / "final_summary.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_release_candidate_artifact(
    *,
    run_dir: str,
    task_id: str,
    project: str,
    title: str,
    final_summary: dict[str, Any],
) -> dict[str, Any]:
    rd = Path(run_dir)
    inv = _read_json_file(rd / "investigation.json")
    files_changed = final_summary.get("files_changed")
    if not isinstance(files_changed, list):
        files_changed = []
    verification_status = str(final_summary.get("verification_status") or "unknown")
    rc: dict[str, Any] = {
        "task_id": task_id,
        "project": project,
        "title": title,
        "run_dir": run_dir,
        "files_changed": files_changed,
        "verification_status": verification_status,
        "summary": (
            f"Autonomous runner reached fixed outcome with {len(files_changed)} changed files. "
            "Awaiting human approval for next phase."
        ),
        "risk": str(inv.get("risk") or "unknown"),
        "status": "release-candidate-ready",
    }
    try:
        (rd / "release_candidate.json").write_text(json.dumps(rc, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("autonomous_runner_launcher: failed to write release_candidate.json: %s", exc)
    return rc


def _safe_update_status(page_id: str, status: str, append_comment: str = "") -> None:
    if not page_id:
        return
    try:
        from app.services.notion_tasks import update_notion_task_status
        update_notion_task_status(page_id, status, append_comment=append_comment or None)
    except Exception:
        logger.debug("autonomous_runner_launcher: status update failed page=%s status=%s", page_id[:12], status)


def _safe_update_metadata(page_id: str, metadata: dict[str, Any], append_comment: str = "") -> None:
    if not page_id:
        return
    try:
        from app.services.notion_tasks import update_notion_task_metadata
        update_notion_task_metadata(page_id, metadata, append_comment=append_comment or None)
    except Exception:
        logger.debug("autonomous_runner_launcher: metadata update failed page=%s", page_id[:12])


def _mark_notion_created(page_id: str, project: str, title: str) -> None:
    if not page_id:
        return
    _safe_update_status(page_id, "ready-for-investigation", append_comment="Autonomous runner accepted from Telegram intake.")
    _safe_update_metadata(page_id, {"environment": "prod", "repo": "automated-trading-platform"}, append_comment=f"Runner created for {project}: {title[:140]}")


def _link_notion_runner(page_id: str, task_id: str, run_dir: str) -> None:
    if not page_id:
        return
    _safe_update_metadata(page_id, {"final_result": f"runner_task_id={task_id} run_dir={run_dir}"}, append_comment=f"Runner linkage: task_id={task_id} run_dir={run_dir}")


def _mark_notion_fixed(page_id: str, final_summary: dict[str, Any], task_id: str, run_dir: str) -> None:
    if not page_id:
        return
    _safe_update_status(page_id, "done", append_comment="Autonomous runner finished with fixed status.")
    _safe_update_metadata(page_id, {"final_result": f"fixed task_id={task_id} run_dir={run_dir}"}, append_comment=f"Runner fixed. iterations={final_summary.get('iterations_run')}")


def _mark_notion_blocked(page_id: str, reason: str) -> None:
    if not page_id:
        return
    _safe_update_status(page_id, "blocked", append_comment=f"Autonomous runner blocked: {reason[:300]}")
    _safe_update_metadata(page_id, {"blocker_reason": reason[:500]})


def _mark_notion_release_candidate_ready(page_id: str, rc: dict[str, Any], task_id: str, run_dir: str) -> None:
    if not page_id:
        return
    _safe_update_status(
        page_id,
        "release-candidate-ready",
        append_comment="Autonomous runner fixed. Release candidate is ready for human approval.",
    )
    _safe_update_metadata(
        page_id,
        {
            "final_result": f"release_candidate_ready task_id={task_id} run_dir={run_dir}",
            "test_status": str(rc.get("verification_status") or "unknown"),
            "risk_level": str(rc.get("risk") or "unknown"),
        },
        append_comment=f"Release candidate artifact: {run_dir}/release_candidate.json",
    )


def _notify_ops(event: str, project: str, title: str, *, task_id: str, run_dir: str, status: str) -> None:
    try:
        from app.services.telegram_notifier import telegram_notifier
        short_run = run_dir[-80:] if run_dir else "-"
        msg = (
            f"[AR] {event}\nproject={project}\ntitle={title[:120]}\n"
            f"task_id={task_id or '-'}\nrun={short_run}\nstatus={status}"
        )
        telegram_notifier.send_message(msg, chat_destination="ops")
    except Exception:
        logger.debug("autonomous_runner_launcher: telegram notify failed event=%s", event)


def _notify_release_candidate_ready(
    project: str,
    title: str,
    *,
    task_id: str,
    run_dir: str,
    rc: dict[str, Any],
    launch_id: str,
) -> None:
    try:
        from app.services.telegram_notifier import telegram_notifier
        files_changed = rc.get("files_changed")
        if not isinstance(files_changed, list):
            files_changed = []
        msg = (
            "[AR] release candidate ready\n"
            f"project={project}\n"
            f"title={title[:120]}\n"
            f"task_id={task_id or '-'}\n"
            f"run={run_dir[-80:] if run_dir else '-'}\n"
            f"files_changed={len(files_changed)}\n"
            f"verification={rc.get('verification_status')}\n"
            "status=release-candidate-ready"
        )
        buttons = [
            [
                {"text": "✅ Approve", "callback_data": f"rc_approve:{launch_id}"},
                {"text": "❌ Reject", "callback_data": f"rc_reject:{launch_id}"},
            ]
        ]
        telegram_notifier.send_message_with_buttons(msg, buttons)
    except Exception:
        logger.debug("autonomous_runner_launcher: telegram notify failed event=release_candidate_ready")


def approve_release_candidate(*, repo_path: str, launch_id: str, approver: str, note: str = "") -> dict[str, Any]:
    """
    Placeholder hook: mark launch as approved for future deploy phase.
    No deploy is executed in MVP v9.
    """
    rp = Path(repo_path).resolve()
    state = _read_state(rp)
    rec = _get_record(state, launch_id)
    if not rec:
        return {"ok": False, "error": "launch not found"}
    current_status = str(rec.get("status") or "").strip()
    if current_status != "release_candidate_ready":
        return {"ok": False, "error": f"invalid status for approval: {current_status}"}
    decided_at = time.time()
    rec["approval"] = {
        "decision": "approved",
        "approver": (approver or "").strip(),
        "decided_by": (approver or "").strip(),
        "note": (note or "").strip()[:500],
        "decided_at": decided_at,
    }
    run_dir = str(rec.get("run_dir") or "").strip()
    task_id = str(rec.get("runner_task_id") or "").strip()
    if not run_dir:
        return {"ok": False, "error": "missing run_dir"}
    deploy_request = _write_deploy_request_artifact(
        repo_path=rp,
        launch_id=launch_id,
        run_dir=run_dir,
        task_id=task_id,
        approved_by=(approver or "").strip(),
        approved_at=decided_at,
    )
    rec["status"] = "deploy_requested"
    rec["finished_at"] = float(rec.get("finished_at") or 0) or time.time()
    _write_state(rp, state)
    if rec.get("notion_page_id"):
        _safe_update_status(
            str(rec.get("notion_page_id")),
            "awaiting-deploy-approval",
            append_comment="Release candidate approved by human; deploy requested.",
        )
        _safe_update_metadata(
            str(rec.get("notion_page_id")),
            {
                "deploy_approval": f"approved by {approver}",
                "final_result": f"approved launch_id={launch_id} deploy_request={run_dir}/deploy_request.json",
                "test_status": f"decision=approved; decided_by={approver}; decided_at={int(decided_at)}",
            },
            append_comment=f"Approval note: {(note or '').strip()[:240]}",
        )
    _notify_deploy_started(
        project=str(rec.get("project") or ""),
        title=str(rec.get("title") or ""),
        task_id=task_id,
        run_dir=run_dir,
        launch_id=launch_id,
    )
    _spawn_deploy_worker(repo_path=rp, launch_id=launch_id)
    return {"ok": True, "status": "approved", "deploy_request": deploy_request}


def reject_release_candidate(*, repo_path: str, launch_id: str, approver: str, note: str = "") -> dict[str, Any]:
    """
    Placeholder hook: mark launch as rejected and request revision.
    """
    rp = Path(repo_path).resolve()
    state = _read_state(rp)
    rec = _get_record(state, launch_id)
    if not rec:
        return {"ok": False, "error": "launch not found"}
    decided_at = time.time()
    rec["approval"] = {
        "decision": "rejected",
        "approver": (approver or "").strip(),
        "decided_by": (approver or "").strip(),
        "note": (note or "").strip()[:500],
        "decided_at": decided_at,
    }
    rec["status"] = "rejected"
    rec["finished_at"] = float(rec.get("finished_at") or 0) or time.time()
    _write_state(rp, state)
    if rec.get("notion_page_id"):
        _safe_update_status(str(rec.get("notion_page_id")), "blocked", append_comment="Release candidate rejected by human.")
        _safe_update_metadata(
            str(rec.get("notion_page_id")),
            {
                "deploy_approval": f"rejected by {approver}",
                "blocker_reason": (note or "Rejected in release candidate review.")[:300],
                "test_status": f"decision=rejected; decided_by={approver}; decided_at={int(decided_at)}",
            },
            append_comment=f"Rejection note: {(note or '').strip()[:240]}",
        )
    return {"ok": True, "status": "rejected"}


def _default_deploy_commands() -> list[str]:
    raw = (os.environ.get("AUTONOMOUS_DEPLOY_COMMANDS") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(";;")]
        return [p for p in parts if p]
    return [
        "docker compose --profile aws up -d --build backend-aws",
        "docker compose ps",
    ]


def _write_deploy_request_artifact(
    *,
    repo_path: Path,
    launch_id: str,
    run_dir: str,
    task_id: str,
    approved_by: str,
    approved_at: float,
) -> dict[str, Any]:
    req = {
        "task_id": task_id,
        "launch_id": launch_id,
        "run_dir": run_dir,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "deploy_commands": _default_deploy_commands(),
        "expected_checks": [
            "docker compose command exits with code 0",
            "docker compose ps contains backend-aws",
        ],
        "status": "deploy_requested",
    }
    try:
        rd = Path(run_dir)
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "deploy_request.json").write_text(json.dumps(req, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("autonomous_runner_launcher: failed to write deploy_request.json: %s", exc)
    return req


def _spawn_deploy_worker(*, repo_path: Path, launch_id: str) -> None:
    payload = {"repo_path": str(repo_path), "launch_id": launch_id}
    cmd = [sys.executable, str(Path(__file__).resolve()), "--deploy-worker-payload", json.dumps(payload)]
    env_vars = os.environ.copy()
    backend_path = str(repo_path / "backend")
    py_path = env_vars.get("PYTHONPATH", "").strip()
    env_vars["PYTHONPATH"] = backend_path if not py_path else f"{backend_path}:{py_path}"
    try:
        subprocess.Popen(
            cmd,
            cwd=str(repo_path),
            env=env_vars,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        _update_launch_record(repo_path, launch_id, status="deploy_failed", error=f"deploy worker start failed: {exc}", finished=True)


def _deploy_worker_main(worker_payload: dict[str, Any]) -> int:
    repo_path = Path(str(worker_payload.get("repo_path") or ".")).resolve()
    launch_id = str(worker_payload.get("launch_id") or "").strip()
    state = _read_state(repo_path)
    rec = _get_record(state, launch_id)
    if not rec:
        return 1
    run_dir = str(rec.get("run_dir") or "").strip()
    task_id = str(rec.get("runner_task_id") or "").strip()
    page_id = str(rec.get("notion_page_id") or "").strip()
    project = str(rec.get("project") or "").strip()
    title = str(rec.get("title") or "").strip()
    if not run_dir:
        _update_launch_record(repo_path, launch_id, status="deploy_failed", error="missing run_dir", finished=True)
        _safe_update_status(page_id, "blocked", append_comment="Deploy failed: missing run_dir.")
        _notify_deploy_failed(project=project, title=title, task_id=task_id, run_dir=run_dir, reason="missing run_dir")
        return 1

    _update_launch_record(repo_path, launch_id, status="deploying")
    _safe_update_status(page_id, "deploying", append_comment="Controlled deploy execution started.")
    _safe_update_metadata(page_id, {"final_result": f"deploying launch_id={launch_id} run_dir={run_dir}"})
    run_dir_path = Path(run_dir)
    result = _run_controlled_deploy(repo_path=repo_path, run_dir=run_dir_path, launch_id=launch_id, task_id=task_id)
    ok = bool(result.get("success"))
    if ok:
        retries = max(1, int((os.environ.get("AUTONOMOUS_POST_DEPLOY_RETRIES") or "2").strip() or "2"))
        delay_s = max(1, int((os.environ.get("AUTONOMOUS_POST_DEPLOY_RETRY_DELAY_SECONDS") or "2").strip() or "2"))
        post: dict[str, Any] = {}
        post_ok = False
        for attempt in range(1, retries + 1):
            post = _run_post_deploy_checks(
                repo_path=repo_path,
                run_dir=run_dir_path,
                launch_id=launch_id,
                task_id=task_id,
                attempt=attempt,
                max_attempts=retries,
            )
            post_ok = bool(post.get("success"))
            if post_ok:
                break
            if attempt < retries:
                time.sleep(delay_s)
        if post_ok:
            _update_launch_record(repo_path, launch_id, status="deployed", error="", finished=True)
            _safe_update_status(page_id, "deployed", append_comment="Controlled deploy + post-deploy checks passed.")
            _safe_update_metadata(page_id, {"final_result": f"deployed launch_id={launch_id} run_dir={run_dir}"})
            _write_deploy_summary(
                run_dir=run_dir_path,
                deploy_command_status=str(result.get("status") or ""),
                post_check_status=str(post.get("status") or "passed"),
                final_status="deployed",
                checks_passed=int(post.get("checks_passed") or 0),
                checks_failed=int(post.get("checks_failed") or 0),
                final_error="",
            )
            _notify_deploy_succeeded(project=project, title=title, task_id=task_id, run_dir=run_dir)
            return 0
        reason = str(post.get("error") or "post deploy checks failed")
        _update_launch_record(repo_path, launch_id, status="post_deploy_failed", error=reason, finished=True)
        _safe_update_status(page_id, "blocked", append_comment=f"Post-deploy checks failed: {reason[:240]}")
        _safe_update_metadata(page_id, {"blocker_reason": reason[:300]})
        _write_deploy_summary(
            run_dir=run_dir_path,
            deploy_command_status=str(result.get("status") or ""),
            post_check_status=str(post.get("status") or "failed"),
            final_status="post_deploy_failed",
            checks_passed=int(post.get("checks_passed") or 0),
            checks_failed=int(post.get("checks_failed") or 0),
            final_error=reason,
        )
        _notify_deploy_failed(
            project=project,
            title=title,
            task_id=task_id,
            run_dir=run_dir,
            reason=f"post_deploy_failed: {reason}",
        )
        return 1

    reason = str(result.get("error") or "deploy failed")
    _update_launch_record(repo_path, launch_id, status="deploy_failed", error=reason, finished=True)
    _safe_update_status(page_id, "blocked", append_comment=f"Controlled deploy failed: {reason[:240]}")
    _safe_update_metadata(page_id, {"blocker_reason": reason[:300]})
    _write_deploy_summary(
        run_dir=run_dir_path,
        deploy_command_status=str(result.get("status") or "deploy_failed"),
        post_check_status="not_run",
        final_status="deploy_failed",
        checks_passed=0,
        checks_failed=0,
        final_error=reason,
    )
    _notify_deploy_failed(
        project=project,
        title=title,
        task_id=task_id,
        run_dir=run_dir,
        reason=f"deploy_command_failed: {reason}",
    )
    return 1


def _validate_deploy_command(command: str) -> tuple[bool, str, list[str]]:
    if not command:
        return False, "empty command", []
    if any(x in command for x in ["&&", "||", ";", "|", "$(", "`", ">", "<"]):
        return False, "shell chaining/redirection not allowed", []
    lowered = command.lower()
    if any(tok in f" {lowered} " for tok in [" rm ", " mv ", " chmod ", " chown ", " kill ", " sudo "]):
        return False, "dangerous token not allowed", []
    try:
        import shlex

        argv = shlex.split(command)
    except ValueError:
        return False, "command parse failed", []
    if not argv:
        return False, "empty argv", []
    health_url = (os.environ.get("AUTONOMOUS_POST_DEPLOY_HEALTH_URL") or "").strip() or _POST_DEPLOY_HEALTH_URL_DEFAULT
    allowed = {
        ("docker", "compose", "--profile", "aws", "up", "-d", "--build", "backend-aws"),
        ("docker", "compose", "up", "-d", "--build", "backend-aws"),
        ("docker", "compose", "ps"),
        ("docker", "compose", "config"),
        ("docker", "logs", "backend-aws"),
        ("curl", "-fsS", "--max-time", "5", health_url),
    }
    if tuple(argv) in allowed:
        return True, "", argv
    return False, "command does not match deploy allowlist", []


def _run_controlled_deploy(*, repo_path: Path, run_dir: Path, launch_id: str, task_id: str) -> dict[str, Any]:
    req = _read_json_file(run_dir / "deploy_request.json")
    commands = req.get("deploy_commands")
    if not isinstance(commands, list):
        commands = []
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    artifacts: list[str] = []
    observations: list[str] = []
    commands_run: list[str] = []
    notes: list[str] = []
    any_failure = False

    for idx, raw_cmd in enumerate(commands, start=1):
        cmd = str(raw_cmd or "").strip()
        ok, reason, argv = _validate_deploy_command(cmd)
        stdout_path = artifacts_dir / f"deploy_cmd_{idx}.stdout.txt"
        stderr_path = artifacts_dir / f"deploy_cmd_{idx}.stderr.txt"
        artifacts.extend([str(stdout_path), str(stderr_path)])
        if not ok:
            any_failure = True
            notes.append(reason)
            observations.append(f"Rejected deploy command: {cmd}")
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(reason, encoding="utf-8")
            results.append(
                {
                    "command": cmd,
                    "exit_code": -1,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "rejected",
                }
            )
            continue
        commands_run.append(cmd)
        try:
            proc = subprocess.run(
                argv,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            stdout_path.write_text(proc.stdout or "", encoding="utf-8")
            stderr_path.write_text(proc.stderr or "", encoding="utf-8")
            if int(proc.returncode) != 0:
                any_failure = True
                observations.append(f"Deploy command failed exit={proc.returncode}: {cmd}")
            results.append(
                {
                    "command": cmd,
                    "exit_code": int(proc.returncode),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "ok" if int(proc.returncode) == 0 else "failed",
                }
            )
        except Exception as exc:
            any_failure = True
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(str(exc), encoding="utf-8")
            observations.append(f"Deploy execution error: {cmd}")
            results.append(
                {
                    "command": cmd,
                    "exit_code": 1,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "failed",
                }
            )

    status = "deployed" if (commands_run and not any_failure) else "deploy_failed"
    out = {
        "task_id": task_id,
        "launch_id": launch_id,
        "run_dir": str(run_dir),
        "status": status,
        "commands_run": commands_run,
        "results": results,
        "observations": observations,
        "artifacts": artifacts,
        "notes": "; ".join(notes) if notes else "Controlled deploy execution finished.",
        "success": status == "deployed",
        "error": "" if status == "deployed" else (observations[-1] if observations else "deploy_failed"),
    }
    try:
        (run_dir / "deploy_result.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("autonomous_runner_launcher: failed to write deploy_result.json: %s", exc)
    return out


def _run_post_deploy_checks(
    *,
    repo_path: Path,
    run_dir: Path,
    launch_id: str,
    task_id: str,
    attempt: int = 1,
    max_attempts: int = 1,
) -> dict[str, Any]:
    expect_backend = (os.environ.get("AUTONOMOUS_POST_DEPLOY_EXPECT_CONTAINS") or "").strip() or "backend-aws"
    health_url = (os.environ.get("AUTONOMOUS_POST_DEPLOY_HEALTH_URL") or "").strip() or _POST_DEPLOY_HEALTH_URL_DEFAULT
    health_expect = (
        (os.environ.get("AUTONOMOUS_POST_DEPLOY_HEALTH_EXPECT_CONTAINS") or "").strip()
        or _POST_DEPLOY_HEALTH_EXPECT_DEFAULT
    )
    checks = [
        {
            "name": "compose_config_valid",
            "command": "docker compose config",
            "expect_contains": "",
        },
        {
            "name": "local_ping_fast",
            "command": f"curl -fsS --max-time 5 {health_url}",
            "expect_contains": health_expect,
        },
        {
            "name": "compose_ps_backend",
            "command": "docker compose ps",
            "expect_contains": expect_backend,
        }
    ]
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    artifacts: list[str] = []
    observations: list[str] = []
    all_ok = True
    checks_passed = 0
    checks_failed = 0
    for idx, check in enumerate(checks, start=1):
        command = str(check.get("command") or "").strip()
        ok, reason, argv = _validate_deploy_command(command)
        stdout_path = artifacts_dir / f"post_deploy_check_{idx}.stdout.txt"
        stderr_path = artifacts_dir / f"post_deploy_check_{idx}.stderr.txt"
        artifacts.extend([str(stdout_path), str(stderr_path)])
        if not ok:
            all_ok = False
            stderr_path.write_text(reason, encoding="utf-8")
            stdout_path.write_text("", encoding="utf-8")
            results.append(
                {
                    "name": check.get("name"),
                    "command": command,
                    "exit_code": -1,
                    "contains_ok": False,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "rejected",
                }
            )
            observations.append(f"Post-deploy check rejected: {command}")
            checks_failed += 1
            continue
        try:
            proc = subprocess.run(argv, cwd=str(repo_path), capture_output=True, text=True, timeout=120, check=False)
            out = proc.stdout or ""
            err = proc.stderr or ""
            stdout_path.write_text(out, encoding="utf-8")
            stderr_path.write_text(err, encoding="utf-8")
            expect_contains = str(check.get("expect_contains") or "")
            contains = (not expect_contains) or (expect_contains in out)
            check_ok = int(proc.returncode) == 0 and contains
            if not check_ok:
                all_ok = False
                checks_failed += 1
                observations.append(
                    f"Post-deploy check failed name={check.get('name')} exit={proc.returncode} contains={contains}"
                )
            else:
                checks_passed += 1
            results.append(
                {
                    "name": check.get("name"),
                    "command": command,
                    "exit_code": int(proc.returncode),
                    "contains_ok": contains,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "ok" if check_ok else "failed",
                }
            )
        except Exception as exc:
            all_ok = False
            checks_failed += 1
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(str(exc), encoding="utf-8")
            observations.append(f"Post-deploy check error name={check.get('name')}: {exc}")
            results.append(
                {
                    "name": check.get("name"),
                    "command": command,
                    "exit_code": 1,
                    "contains_ok": False,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "status": "failed",
                }
            )
    status = "passed" if all_ok else "failed"
    out = {
        "task_id": task_id,
        "launch_id": launch_id,
        "run_dir": str(run_dir),
        "status": status,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "checks": checks,
        "results": results,
        "observations": observations,
        "artifacts": artifacts,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "success": all_ok,
        "error": "" if all_ok else (observations[-1] if observations else "post_deploy_failed"),
    }
    try:
        (run_dir / "post_deploy_check.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("autonomous_runner_launcher: failed to write post_deploy_check.json: %s", exc)
    return out


def _write_deploy_summary(
    *,
    run_dir: Path,
    deploy_command_status: str,
    post_check_status: str,
    final_status: str,
    checks_passed: int,
    checks_failed: int,
    final_error: str,
) -> None:
    summary = {
        "deploy_command_status": deploy_command_status,
        "post_check_status": post_check_status,
        "final_status": final_status,
        "checks_passed": int(checks_passed),
        "checks_failed": int(checks_failed),
        "final_error": (final_error or "").strip(),
    }
    try:
        (run_dir / "deploy_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("autonomous_runner_launcher: failed to write deploy_summary.json: %s", exc)


def _notify_deploy_started(project: str, title: str, *, task_id: str, run_dir: str, launch_id: str) -> None:
    _notify_ops("deploy started", project, title, task_id=task_id, run_dir=run_dir, status=f"deploy_requested launch_id={launch_id}")


def _notify_deploy_succeeded(project: str, title: str, *, task_id: str, run_dir: str) -> None:
    _notify_ops("deploy succeeded", project, title, task_id=task_id, run_dir=run_dir, status="deploy fully succeeded")


def _notify_deploy_failed(project: str, title: str, *, task_id: str, run_dir: str, reason: str) -> None:
    reason_text = (reason or "").strip()
    if reason_text.startswith("post_deploy_failed:"):
        status = f"post-deploy verification failed | {reason_text[:90]}"
    elif reason_text.startswith("deploy_command_failed:"):
        status = f"deploy command failed | {reason_text[:90]}"
    else:
        status = f"deploy failed | {reason_text[:90]}"
    _notify_ops("deploy failed", project, title, task_id=task_id, run_dir=run_dir, status=status)


def _main() -> int:
    parser = argparse.ArgumentParser(description="autonomous runner launcher worker")
    parser.add_argument("--worker-payload", default="", help="json payload for worker")
    parser.add_argument("--deploy-worker-payload", default="", help="json payload for deploy worker")
    args = parser.parse_args()
    deploy_payload = (args.deploy_worker_payload or "").strip()
    if deploy_payload:
        try:
            obj = json.loads(deploy_payload)
        except json.JSONDecodeError:
            return 1
        return _deploy_worker_main(obj if isinstance(obj, dict) else {})
    payload = (args.worker_payload or "").strip()
    if not payload:
        return 0
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return 1
    return _worker_main(obj if isinstance(obj, dict) else {})


if __name__ == "__main__":
    raise SystemExit(_main())

