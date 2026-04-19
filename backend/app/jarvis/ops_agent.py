"""Ops agent for infrastructure/configuration diagnostics and safe fix proposals."""

from __future__ import annotations

from typing import Any

from app.jarvis.action_policy import DEFAULT_EXECUTION_MODE, get_action_policy
from app.jarvis import ops_tools
from app.jarvis.setup_diagnostics import diagnose_ga4_setup_bundle, diagnose_gsc_setup_bundle

OPS_ACTION_TYPES: set[str] = {
    # diagnose_google_ads_setup is executed in ExecutionAgent (real GAQL + analytics), not here,
    # so ops env/mount heuristics do not block the pipeline with spurious requires_approval.
    # GA4/GSC setup probes run in ExecutionAgent (same retry path as Google Ads).
    "inspect_docker_mounts",
    "inspect_container_env",
    "verify_credentials_mount",
    "fix_credentials_path",
    "update_runtime_env",
    "restart_backend",
}


def _diag(message: str, *, severity: str = "info", code: str = "") -> dict[str, Any]:
    return {
        "severity": severity,
        "message": message,
        "code": code or severity,
    }


def _action_row(action: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "title": str(action.get("title") or "").strip(),
        "action_type": str(action.get("action_type") or "analysis"),
        "params": action.get("params") if isinstance(action.get("params"), dict) else {},
        "execution_mode": mode,
        "priority_score": int(action.get("priority_score", 0) or 0),
    }


def _contains_any(lines: list[str], *needles: str) -> bool:
    hay = "\n".join(lines).lower()
    return any(n.lower() in hay for n in needles)


class OpsAgent:
    name = "ops"

    def run(
        self,
        prompt: str,
        plan: dict[str, Any],
        research: dict[str, Any] | None,
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        _ = prompt, plan
        actions = [
            a
            for a in (strategy.get("actions") or [])
            if isinstance(a, dict) and str(a.get("action_type") or "").strip().lower() in OPS_ACTION_TYPES
        ]
        diagnostics: list[dict[str, Any]] = []
        proposed_fixes: list[dict[str, Any]] = []
        auto_executed: list[dict[str, Any]] = []
        waiting_for_approval: list[dict[str, Any]] = []
        waiting_for_input: list[dict[str, Any]] = []

        if not actions:
            return {
                "diagnostics": [],
                "proposed_fixes": [],
                "auto_executed": [],
                "waiting_for_approval": [],
                "waiting_for_input": [],
                "summary": "No ops actions in strategy.",
                "success": True,
            }

        for action in actions:
            action_type = str(action.get("action_type") or "").strip().lower()
            policy = get_action_policy(action_type)
            mode = str(action.get("execution_mode") or policy.get("execution_mode") or DEFAULT_EXECUTION_MODE).strip().lower()
            row = _action_row(action, mode)
            if mode == "requires_input":
                waiting_for_input.append(row)
                continue
            if mode == "requires_approval":
                waiting_for_approval.append(row)
                proposed_fixes.append(
                    {
                        "action_type": action_type,
                        "title": row["title"] or action_type,
                        "approval_text": self._approval_text_for_action(action_type, row.get("params") or {}),
                        "priority_score": row["priority_score"],
                    }
                )
                continue

            result = self._run_auto_action(action_type, row.get("params") or {}, research or {})
            auto_executed.append(
                {
                    "action_type": action_type,
                    "title": row["title"] or action_type,
                    "execution_mode": mode,
                    "priority_score": row["priority_score"],
                    "result": result,
                }
            )
            diagnostics.extend([x for x in (result.get("diagnostics") or []) if isinstance(x, dict)])
            proposed_fixes.extend([x for x in (result.get("proposed_fixes") or []) if isinstance(x, dict)])
            waiting_for_approval.extend([x for x in (result.get("waiting_for_approval") or []) if isinstance(x, dict)])
            waiting_for_input.extend([x for x in (result.get("waiting_for_input") or []) if isinstance(x, dict)])

        if waiting_for_approval and not any(
            "restart backend" in str(x.get("title") or "").lower() for x in waiting_for_approval
        ):
            if any(
                "backend restart required" in str(d.get("message") or "").lower()
                for d in diagnostics
            ):
                waiting_for_approval.append(
                    {
                        "title": "Restart backend service",
                        "action_type": "restart_backend",
                        "params": {},
                        "execution_mode": "requires_approval",
                        "priority_score": 92,
                    }
                )

        ok = not any(str(d.get("severity") or "").lower() == "error" for d in diagnostics)
        return {
            "diagnostics": diagnostics,
            "proposed_fixes": proposed_fixes,
            "auto_executed": auto_executed,
            "waiting_for_approval": waiting_for_approval,
            "waiting_for_input": waiting_for_input,
            "summary": self._build_summary(diagnostics, proposed_fixes, waiting_for_approval),
            "success": ok,
        }

    def _run_auto_action(self, action_type: str, params: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
        if action_type == "inspect_docker_mounts":
            container = str(params.get("container_name") or "backend-aws")
            result = ops_tools.inspect_container_mounts(container)
            return {
                "diagnostics": [
                    _diag(
                        f"Inspected mounts for container '{container}' ({int(result.get('count', 0) or 0)} mounts).",
                        severity="info",
                        code="inspect_mounts",
                    )
                ],
                "proposed_fixes": [],
                "waiting_for_approval": [],
                "waiting_for_input": [],
                "result": result,
            }
        if action_type == "inspect_container_env":
            container = str(params.get("container_name") or "backend-aws")
            prefixes = params.get("env_prefixes") if isinstance(params.get("env_prefixes"), list) else None
            result = ops_tools.inspect_container_env(container, prefixes)
            return {
                "diagnostics": [
                    _diag(
                        f"Inspected env for container '{container}' ({int(result.get('count', 0) or 0)} keys).",
                        severity="info",
                        code="inspect_env",
                    )
                ],
                "proposed_fixes": [],
                "waiting_for_approval": [],
                "waiting_for_input": [],
                "result": result,
            }
        if action_type == "diagnose_google_ads_setup":
            return self._diagnose_google_ads_setup(params, research)
        if action_type == "diagnose_ga4_setup":
            return diagnose_ga4_setup_bundle(params)
        if action_type == "diagnose_gsc_setup":
            return diagnose_gsc_setup_bundle(params)
        if action_type == "verify_credentials_mount":
            return self._verify_credentials_mount(params)
        return {
            "diagnostics": [_diag(f"Unsupported auto action: {action_type}", severity="warning", code="unsupported")],
            "proposed_fixes": [],
            "waiting_for_approval": [],
            "waiting_for_input": [],
        }

    def _diagnose_google_ads_setup(self, params: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
        container = str(params.get("container_name") or "backend-aws").strip()
        env_prefixes = ["JARVIS_GOOGLE_ADS_", "GOOGLE_"]
        env_res = ops_tools.inspect_container_env(container, env_prefixes=env_prefixes)
        mounts_res = ops_tools.inspect_container_mounts(container)
        env_map = env_res.get("env") if isinstance(env_res.get("env"), dict) else {}

        required_env = [
            "JARVIS_GOOGLE_ADS_CREDENTIALS_JSON",
            "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN",
            "JARVIS_GOOGLE_ADS_CUSTOMER_ID",
        ]
        missing_env = [k for k in required_env if not str(env_map.get(k) or "").strip()]
        diagnostics: list[dict[str, Any]] = []
        if missing_env:
            diagnostics.append(
                _diag(
                    "Google Ads is not configured: missing env vars in running container: "
                    + ", ".join(missing_env),
                    severity="error",
                    code="google_ads_missing_env",
                )
            )

        creds_path = str(env_map.get("JARVIS_GOOGLE_ADS_CREDENTIALS_JSON") or params.get("credentials_path") or "").strip()
        in_container = {"success": False, "exists": False, "path": creds_path}
        if creds_path:
            in_container = ops_tools.check_path_in_container(container, creds_path)
            if not in_container.get("exists"):
                diagnostics.append(
                    _diag(
                        "Google Ads credentials file is not present inside the running container.",
                        severity="error",
                        code="google_ads_missing_file_in_container",
                    )
                )

        mounts = mounts_res.get("mounts") if isinstance(mounts_res.get("mounts"), list) else []
        host_sources = [str(m.get("source") or "") for m in mounts if isinstance(m, dict)]
        mount_hit = None
        for m in mounts:
            if not isinstance(m, dict):
                continue
            dst = str(m.get("destination") or "")
            if creds_path and dst and creds_path.startswith(dst.rstrip("/") + "/"):
                mount_hit = m
                break
            if creds_path and dst == creds_path:
                mount_hit = m
                break

        host_path = str(params.get("host_credentials_path") or "").strip()
        host_exists = None
        if host_path:
            host_exists = ops_tools.check_path_on_host(host_path)
            if not host_exists.get("exists"):
                diagnostics.append(
                    _diag(
                        "Expected Google Ads credentials file does not exist on host path.",
                        severity="error",
                        code="google_ads_host_file_missing",
                    )
                )

        if creds_path and not mount_hit:
            diagnostics.append(
                _diag(
                    "Google Ads credentials path is not covered by current container mounts (host/container path mismatch).",
                    severity="error",
                    code="google_ads_mount_mismatch",
                )
            )
        elif mount_hit and host_path:
            src = str(mount_hit.get("source") or "")
            if src and host_path and not host_path.startswith(src):
                diagnostics.append(
                    _diag(
                        "Google Ads credentials host path does not match mounted source path.",
                        severity="error",
                        code="google_ads_host_mount_mismatch",
                    )
                )

        findings = [str(x) for x in (research.get("findings") or []) if isinstance(x, str)]
        if _contains_any(findings, "not configured", "google ads") and not diagnostics:
            diagnostics.append(
                _diag(
                    "Google Ads reported as not configured, but runtime checks look complete; backend restart required.",
                    severity="warning",
                    code="google_ads_restart_required",
                )
            )

        proposed_fixes: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        if any(d["code"] == "google_ads_missing_env" for d in diagnostics):
            proposed_fixes.append(
                {
                    "action_type": "update_runtime_env",
                    "title": "Set missing Google Ads env vars in runtime env",
                    "execution_mode": "requires_approval",
                    "priority_score": 95,
                }
            )
            waiting.append(
                {
                    "action_type": "update_runtime_env",
                    "title": "Update runtime env with Google Ads values",
                    "params": {"keys": missing_env},
                    "execution_mode": "requires_approval",
                    "priority_score": 95,
                }
            )
        if any(d["code"] in {"google_ads_mount_mismatch", "google_ads_host_mount_mismatch"} for d in diagnostics):
            proposed_fixes.append(
                {
                    "action_type": "fix_credentials_path",
                    "title": "Move Google Ads credentials into mounted secrets directory",
                    "execution_mode": "requires_approval",
                    "priority_score": 94,
                }
            )
            waiting.append(
                {
                    "action_type": "fix_credentials_path",
                    "title": "Fix Google Ads credentials mount path",
                    "params": {
                        "host_credentials_path": host_path,
                        "mount_sources": host_sources[:6],
                    },
                    "execution_mode": "requires_approval",
                    "priority_score": 94,
                }
            )
        if diagnostics:
            proposed_fixes.append(
                {
                    "action_type": "restart_backend",
                    "title": "Restart backend to apply latest runtime configuration",
                    "execution_mode": "requires_approval",
                    "priority_score": 90,
                }
            )
            waiting.append(
                {
                    "action_type": "restart_backend",
                    "title": "Restart backend service",
                    "params": {},
                    "execution_mode": "requires_approval",
                    "priority_score": 90,
                }
            )
        if not diagnostics:
            diagnostics.append(
                _diag("Google Ads runtime configuration appears complete.", severity="info", code="google_ads_ok")
            )

        return {
            "diagnostics": diagnostics,
            "proposed_fixes": proposed_fixes,
            "waiting_for_approval": waiting,
            "waiting_for_input": [],
            "result": {
                "env_inspection_ok": bool(env_res.get("success")),
                "mounts_inspection_ok": bool(mounts_res.get("success")),
                "credentials_path": creds_path,
                "credentials_exists_in_container": bool(in_container.get("exists")),
                "missing_env_vars": missing_env,
            },
        }

    def _verify_credentials_mount(self, params: dict[str, Any]) -> dict[str, Any]:
        container = str(params.get("container_name") or "backend-aws")
        path = str(params.get("path") or "").strip()
        if not path:
            return {
                "diagnostics": [
                    _diag("verify_credentials_mount requires a path parameter.", severity="warning", code="missing_path")
                ],
                "proposed_fixes": [],
                "waiting_for_approval": [],
                "waiting_for_input": [],
            }
        in_container = ops_tools.check_path_in_container(container, path)
        if in_container.get("exists"):
            return {
                "diagnostics": [_diag("Credentials file exists in container mount.", severity="info", code="mount_ok")],
                "proposed_fixes": [],
                "waiting_for_approval": [],
                "waiting_for_input": [],
            }
        return {
            "diagnostics": [
                _diag(
                    "Credentials file exists on host but not in mounted secrets directory.",
                    severity="error",
                    code="mount_missing_file",
                )
            ],
            "proposed_fixes": [
                {
                    "action_type": "fix_credentials_path",
                    "title": "Move credentials file into mounted secrets directory",
                    "execution_mode": "requires_approval",
                    "priority_score": 92,
                }
            ],
            "waiting_for_approval": [
                {
                    "action_type": "fix_credentials_path",
                    "title": "Move credentials file into mounted secrets directory",
                    "params": {"path": path},
                    "execution_mode": "requires_approval",
                    "priority_score": 92,
                }
            ],
            "waiting_for_input": [],
        }

    def _approval_text_for_action(self, action_type: str, params: dict[str, Any]) -> str:
        _ = params
        if action_type == "fix_credentials_path":
            return "Approve fix: move Google Ads credentials into mounted secrets directory and restart backend?"
        if action_type == "restart_backend":
            return "Approve fix: restart backend service to load updated settings?"
        if action_type == "update_runtime_env":
            return "Approve fix: update runtime env values and restart backend?"
        return "Approve critical ops fix?"

    def _build_summary(
        self,
        diagnostics: list[dict[str, Any]],
        proposed_fixes: list[dict[str, Any]],
        waiting_for_approval: list[dict[str, Any]],
    ) -> str:
        if not diagnostics and not proposed_fixes:
            return "Ops checks complete with no findings."
        errors = sum(1 for x in diagnostics if str(x.get("severity") or "").lower() == "error")
        warnings = sum(1 for x in diagnostics if str(x.get("severity") or "").lower() == "warning")
        return (
            f"Ops diagnostics complete: {errors} error(s), {warnings} warning(s), "
            f"{len(proposed_fixes)} fix proposal(s), {len(waiting_for_approval)} awaiting approval."
        )
