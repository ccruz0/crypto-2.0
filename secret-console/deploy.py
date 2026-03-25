"""
Apply secrets to ATP runtime: pull from AWS Parameter Store, update env files,
restart Docker Compose service. Uses explicit mappings from mappings.py.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import aws_sync
import mappings
from mappings import DeployTarget, HealthcheckSpec

log = logging.getLogger(__name__)

BACKUP_SUBDIR = ".secret-console-backups"


def _compose_use_sudo() -> bool:
    return os.environ.get("SECRET_CONSOLE_COMPOSE_USE_SUDO", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _compose_cmd_prefix(profile: str) -> list[str]:
    cmd = ["docker", "compose", "--profile", profile]
    if _compose_use_sudo():
        return ["sudo", "-n", *cmd]
    return cmd


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 300,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _docker_compose_available() -> tuple[str, str]:
    p = _run(["docker", "compose", "version"], timeout=30)
    if p.returncode != 0:
        return (
            "FAIL",
            (p.stderr or p.stdout or "docker compose version failed").strip(),
        )
    return "OK", ""


def _compose_config_services(project: Path, profile: str) -> tuple[str, str, list[str]]:
    cmd = _compose_cmd_prefix(profile) + ["config", "--services"]
    p = _run(cmd, cwd=project, timeout=120)
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        return "FAIL", err, []
    services = [s.strip() for s in p.stdout.splitlines() if s.strip()]
    return "OK", "", services


def _file_mode_oct(path: Path) -> str:
    st = path.stat()
    return format(stat.S_IMODE(st.st_mode), "o")


def _read_key_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("#", 1)[0].strip()
        if s.startswith(f"{key}="):
            return line.split("=", 1)[1].strip() if "=" in line else ""
    return None


def _key_present_or_appendable(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    if _read_key_value(path, key) is not None:
        return True
    return os.access(path, os.W_OK)


def precheck_deploy(spec: DeployTarget, project: Path) -> dict[str, Any]:
    """
    Run all checks before mutating files. Returns a ``precheck`` dict with
    per-field status strings (mostly ``OK`` / ``FAIL``) and optional details.
    """
    out: dict[str, Any] = {
        "project_path": "FAIL",
        "env_file": "FAIL",
        "runtime_env_file": "FAIL",
        "files_writable": "FAIL",
        "env_keys": "FAIL",
        "docker_compose": "FAIL",
        "compose_service": "FAIL",
        "runtime_env_mode": "",
    }

    if not project.is_dir():
        out["project_path"] = "FAIL"
        out["detail"] = f"not a directory: {project}"
        return out

    out["project_path"] = "OK"

    env_files = spec.get("env_files") or []
    paths: list[Path] = []
    for entry in env_files:
        paths.append(project / entry["path"])

    env_aws = project / ".env.aws"
    runtime_env = project / "secrets" / "runtime.env"

    if not env_aws.is_file():
        out["env_file"] = "FAIL"
        out["detail"] = f"missing: {env_aws}"
        return out
    out["env_file"] = "OK"

    if not runtime_env.is_file():
        out["runtime_env_file"] = "FAIL"
        out["detail"] = f"missing: {runtime_env}"
        return out
    out["runtime_env_file"] = "OK"

    try:
        out["runtime_env_mode"] = _file_mode_oct(runtime_env)
    except OSError as e:
        out["runtime_env_file"] = "FAIL"
        out["detail"] = f"stat runtime.env: {e}"
        return out

    for fp in paths:
        if not fp.is_file():
            out["files_writable"] = "FAIL"
            out["detail"] = f"missing mapped file: {fp}"
            return out
        if not os.access(fp, os.W_OK):
            out["files_writable"] = "FAIL"
            out["detail"] = f"not writable: {fp}"
            return out
    out["files_writable"] = "OK"

    for entry in env_files:
        fp = project / entry["path"]
        key = entry["key"]
        if not _key_present_or_appendable(fp, key):
            out["env_keys"] = "FAIL"
            out["detail"] = f"key {key!r} not found and cannot append: {fp}"
            return out
    out["env_keys"] = "OK"

    dc, dc_err = _docker_compose_available()
    out["docker_compose"] = dc
    if dc != "OK":
        out["detail"] = dc_err or "docker compose unavailable"
        return out

    profile = spec.get("profile") or ""
    service = spec.get("service") or ""
    if not profile:
        out["compose_service"] = "FAIL"
        out["detail"] = "mapping missing profile"
        return out

    cs, cs_err, svcs = _compose_config_services(project, profile)
    if cs != "OK":
        out["compose_service"] = "FAIL"
        out["detail"] = cs_err or "compose config --services failed"
        return out
    if service and service not in svcs:
        out["compose_service"] = "FAIL"
        out["detail"] = f"service {service!r} not in compose services: {svcs}"
        return out
    out["compose_service"] = "OK"

    return out


def _upsert_env_key(file_path: Path, key: str, value: str) -> None:
    """Set KEY=value in a dotenv-style file; preserve other lines; atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if file_path.exists():
        raw = file_path.read_text(encoding="utf-8")
        lines = raw.splitlines()

    new_line = f"{key}={value}"
    found = False
    out: list[str] = []
    for line in lines:
        s = line.split("#", 1)[0].strip()
        if s.startswith(f"{key}="):
            out.append(new_line)
            found = True
        else:
            out.append(line)
    if not found:
        out.append(new_line)

    text = "\n".join(out) + "\n"
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(file_path)
    # Optional octal mode, e.g. SECRET_CONSOLE_ENV_FILE_MODE=600 (parsed as octal).
    # Default: do not chmod — mode 600 on secrets/runtime.env breaks the container if its
    # UID does not match the file owner (see PermissionError reading runtime.env).
    mode_s = os.environ.get("SECRET_CONSOLE_ENV_FILE_MODE", "").strip()
    if mode_s:
        try:
            file_path.chmod(int(mode_s, 8))
        except ValueError:
            log.warning("invalid SECRET_CONSOLE_ENV_FILE_MODE=%r (use octal, e.g. 600)", mode_s)
        except OSError as e:
            log.warning("chmod failed for %s: %s", file_path, e)
    chown = os.environ.get("SECRET_CONSOLE_SECRETS_CHOWN", "").strip()
    if chown and "secrets" in file_path.parts:
        proc = subprocess.run(
            ["sudo", "-n", "chown", chown, str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            log.warning(
                "chown %s %s failed (need passwordless sudo?): %s",
                chown,
                file_path,
                (proc.stderr or proc.stdout or "").strip(),
            )
        else:
            log.info("chown %s %s", chown, file_path)
    log.info("updated env file %s key=%s", file_path, key)


def _compose_restart(project_path: Path, profile: str, service: str) -> None:
    # recreate so env_file / host env changes are picked up (plain `restart` keeps old env)
    cmd = _compose_cmd_prefix(profile) + [
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        service,
    ]
    log.info("running in %s: %s", project_path, " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(project_path),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        log.error("docker compose up --force-recreate failed: %s", err)
        raise RuntimeError(f"docker compose recreate failed: {err or proc.returncode}")
    log.info("docker compose recreate ok for service=%s", service)


def _backup_dir(project: Path) -> Path:
    return project / BACKUP_SUBDIR


def _backup_files(project: Path, files: list[Path]) -> list[dict[str, str]]:
    bdir = _backup_dir(project)
    bdir.mkdir(parents=True, exist_ok=True)
    backups: list[dict[str, str]] = []
    ts = int(time.time())
    for fp in files:
        if not fp.is_file():
            continue
        try:
            rel = fp.relative_to(project)
            safe = str(rel).replace(os.sep, "_")
        except ValueError:
            safe = fp.name.replace(os.sep, "_")
        dest = bdir / f"{ts}_{safe}.bak"
        shutil.copy2(fp, dest)
        backups.append({"path": str(fp), "backup": str(dest)})
        log.info("backup %s -> %s", fp, dest)
    return backups


def _restore_files(backup_entries: list[dict[str, str]]) -> None:
    for ent in backup_entries:
        src = Path(ent["backup"])
        dst = Path(ent["path"])
        if not src.is_file():
            raise OSError(f"backup missing: {src}")
        shutil.copy2(src, dst)
        log.info("restored %s <- %s", dst, src)


def _compose_service_running(project: Path, profile: str, service: str) -> tuple[bool, str]:
    cmd = _compose_cmd_prefix(profile) + ["ps", service]
    p = _run(cmd, cwd=project, timeout=60)
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return False, (p.stderr or out or "compose ps failed").strip()
    if not out:
        return False, "compose ps: no rows for service"
    lower = out.lower()
    if "up" in lower or "running" in lower:
        return True, out[:500]
    return False, out[:500]


def _healthcheck(
    project: Path,
    profile: str,
    service: str,
    hc: HealthcheckSpec | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"compose_ps": "FAIL", "exec": "SKIP"}
    ok, detail = _compose_service_running(project, profile, service)
    result["compose_ps"] = "OK" if ok else "FAIL"
    result["compose_ps_detail"] = detail
    if not ok:
        return result

    if not hc or not hc.get("exec"):
        result["exec"] = "SKIP"
        return result

    cmd = _compose_cmd_prefix(profile) + ["exec", "-T", service, *hc["exec"]]
    p = _run(cmd, cwd=project, timeout=120)
    if p.returncode == 0:
        result["exec"] = "OK"
    else:
        result["exec"] = "FAIL"
        result["exec_detail"] = (p.stderr or p.stdout or "").strip()[:2000]
    return result


def apply_to_environment(
    environment: str,
    secret_name: str | None = None,
    *,
    target: str | None = None,
) -> dict[str, Any]:
    """
    For mapped secrets: fetch value from AWS, write configured env files under
    project_path, restart the Compose service. Run on the ATP host where paths exist.

    ``target`` is reserved for future SSM/SSH; unused for local-path apply.
    """
    base: dict[str, Any] = {
        "environment": environment,
        "secret_name": secret_name,
        "target": target,
        "precheck": {},
        "backup": [],
        "healthcheck": {},
        "rollback": {"attempted": False, "ok": None, "detail": ""},
        "report": {},
    }

    if not secret_name:
        log.warning("apply_to_environment: secret_name required")
        return {
            **base,
            "ok": False,
            "stub": True,
            "message": "secret_name is required for Apply.",
        }

    spec = mappings.get_deploy_target(secret_name, environment)
    if not spec:
        log.warning(
            "apply_to_environment: no mapping for secret=%s env=%s",
            secret_name,
            environment,
        )
        return {
            **base,
            "ok": False,
            "stub": True,
            "message": (
                f"No deploy mapping for {secret_name!r} ({environment}). "
                "Add it in mappings.py."
            ),
        }

    project = Path(spec["project_path"])
    pre = precheck_deploy(spec, project)
    base["precheck"] = pre

    def _fail(
        msg: str,
        *,
        stub: bool = False,
        updated_files: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = {
            **base,
            "ok": False,
            "stub": stub,
            "message": msg,
            "report": {"phase": "failed", "precheck": pre},
        }
        if updated_files is not None:
            r["updated_files"] = updated_files
        if extra:
            r.update(extra)
        return r

    critical = (
        "project_path",
        "env_file",
        "runtime_env_file",
        "files_writable",
        "env_keys",
        "docker_compose",
        "compose_service",
    )
    for k in critical:
        if pre.get(k) != "OK":
            return _fail(
                pre.get("detail") or f"precheck failed: {k}",
                extra={"report": {"phase": "precheck", "precheck": pre}},
            )

    try:
        value = aws_sync.get_secret(environment, secret_name)
    except KeyError:
        log.error("AWS parameter missing for %s/%s", environment, secret_name)
        return _fail(
            f"AWS parameter missing for {secret_name} ({environment}). "
            "Sync to Parameter Store first.",
            extra={"report": {"phase": "aws", "precheck": pre}},
        )
    except Exception as e:
        log.exception("failed to read secret from AWS")
        return _fail(
            f"AWS read failed: {e}",
            extra={"report": {"phase": "aws", "precheck": pre}},
        )

    env_files = spec.get("env_files") or []
    file_paths = [project / e["path"] for e in env_files]
    backup_entries: list[dict[str, str]] = []
    try:
        backup_entries = _backup_files(project, file_paths)
        base["backup"] = backup_entries
    except OSError as e:
        log.exception("backup failed")
        return _fail(
            f"Backup failed: {e}",
            extra={"report": {"phase": "backup", "precheck": pre}},
        )

    updated_files: list[str] = []
    try:
        for entry in env_files:
            rel = entry["path"]
            key = entry["key"]
            fp = project / rel
            _upsert_env_key(fp, key, value)
            updated_files.append(str(fp))
    except OSError as e:
        log.exception("failed writing env files")
        rb = base["rollback"]
        rb["attempted"] = True
        try:
            _restore_files(backup_entries)
            rb["ok"] = True
        except Exception as re:
            log.exception("rollback after write failure")
            rb["ok"] = False
            rb["detail"] = str(re)
        return {
            **base,
            "ok": False,
            "stub": False,
            "message": f"Failed to write env files: {e}",
            "updated_files": updated_files,
            "rollback": rb,
            "report": {"phase": "write", "precheck": pre, "rollback": rb},
        }

    profile = spec.get("profile", "")
    service = spec.get("service", "")
    if not profile or not service:
        log.error("mapping missing profile or service")
        rb = base["rollback"]
        rb["attempted"] = True
        try:
            _restore_files(backup_entries)
            rb["ok"] = True
        except Exception as re:
            rb["ok"] = False
            rb["detail"] = str(re)
        return {
            **base,
            "ok": False,
            "stub": False,
            "message": "Mapping incomplete: profile and service required.",
            "updated_files": updated_files,
            "rollback": rb,
            "report": {"phase": "mapping", "precheck": pre, "rollback": rb},
        }

    def _do_rollback(reason: str) -> dict[str, Any]:
        rb = base["rollback"]
        rb["attempted"] = True
        try:
            _restore_files(backup_entries)
            rb["ok"] = True
        except Exception as re:
            log.exception("rollback restore failed: %s", reason)
            rb["ok"] = False
            rb["detail"] = str(re)
            return {
                **base,
                "ok": False,
                "stub": False,
                "message": f"{reason}; rollback restore failed: {re}",
                "updated_files": updated_files,
                "healthcheck": base.get("healthcheck", {}),
                "rollback": rb,
                "report": {
                    "phase": "rollback",
                    "precheck": pre,
                    "reason": reason,
                },
            }
        try:
            _compose_restart(project, profile, service)
        except Exception as cre:
            log.exception("rollback compose failed")
            rb["detail"] = (rb.get("detail") or "") + f"; recompose failed: {cre}"
            return {
                **base,
                "ok": False,
                "stub": False,
                "message": f"{reason}; files restored but recompose failed: {cre}",
                "updated_files": updated_files,
                "healthcheck": base.get("healthcheck", {}),
                "rollback": rb,
                "report": {"phase": "rollback_recompose", "precheck": pre},
            }
        return {
            **base,
            "ok": False,
            "stub": False,
            "message": f"{reason}; rolled back and service recreated.",
            "updated_files": updated_files,
            "healthcheck": base.get("healthcheck", {}),
            "rollback": rb,
            "report": {"phase": "rollback_ok", "precheck": pre},
        }

    try:
        _compose_restart(project, profile, service)
    except Exception as e:
        return _do_rollback(str(e))

    hc_spec = spec.get("healthcheck")
    hc_result = _healthcheck(project, profile, service, hc_spec)
    base["healthcheck"] = hc_result

    if hc_result.get("compose_ps") != "OK" or hc_result.get("exec") == "FAIL":
        reason = "Healthcheck failed"
        if hc_result.get("compose_ps") != "OK":
            reason = f"Healthcheck failed (compose_ps: {hc_result.get('compose_ps_detail', '')})"
        elif hc_result.get("exec") == "FAIL":
            reason = f"Healthcheck failed (exec: {hc_result.get('exec_detail', '')})"
        return _do_rollback(reason)

    log.info(
        "apply ok secret=%s env=%s files=%d service=%s",
        secret_name,
        environment,
        len(updated_files),
        service,
    )
    base["rollback"] = {"attempted": False, "ok": True, "detail": ""}
    return {
        **base,
        "ok": True,
        "stub": False,
        "message": (
            f"Applied from AWS: updated {len(updated_files)} file(s), "
            f"recreated compose service {service!r} (profile {profile!r}); "
            "precheck, backup, and healthcheck OK."
        ),
        "updated_files": updated_files,
        "service": service,
        "profile": profile,
        "report": {
            "phase": "complete",
            "precheck": pre,
            "backup_count": len(backup_entries),
            "healthcheck": hc_result,
        },
    }
