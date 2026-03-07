"""
HTTP client for the OpenClaw Gateway OpenResponses API.

Sends structured prompts derived from Notion tasks to OpenClaw for
AI-powered investigation/analysis. Returns plain-text results that
the caller can save to docs/ and post back to Notion.

Endpoint: POST /v1/responses  (must be enabled in openclaw.json)
Auth:     Bearer <gateway token>
Docs:     https://docs.openclaw.ai/gateway/openresponses-http-api
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "http://172.31.3.214:8080"
_DEFAULT_TIMEOUT = 120


def _api_url() -> str:
    return (os.environ.get("OPENCLAW_API_URL") or "").strip() or _DEFAULT_API_URL


def _api_token() -> str:
    return (os.environ.get("OPENCLAW_API_TOKEN") or "").strip()


def _timeout() -> int:
    raw = (os.environ.get("OPENCLAW_TIMEOUT_SECONDS") or "").strip()
    try:
        return int(raw) if raw else _DEFAULT_TIMEOUT
    except ValueError:
        return _DEFAULT_TIMEOUT


def is_openclaw_configured() -> bool:
    """True when both API URL and token are available."""
    return bool(_api_url()) and bool(_api_token())


# ---------------------------------------------------------------------------
# Core HTTP call
# ---------------------------------------------------------------------------

def send_to_openclaw(
    prompt: str,
    *,
    task_id: str = "",
    instructions: str | None = None,
) -> dict[str, Any]:
    """Send a prompt to OpenClaw and return the response.

    Returns ``{"success": True, "content": "...", "raw": {...}}`` on success,
    or ``{"success": False, "content": "", "error": "..."}`` on failure.
    """
    token = _api_token()
    if not token:
        return {"success": False, "content": "", "error": "OPENCLAW_API_TOKEN not set"}

    url = f"{_api_url().rstrip('/')}/v1/responses"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-openclaw-agent-id": "main",
    }

    body: dict[str, Any] = {
        "model": "openclaw",
        "input": prompt,
    }
    if task_id:
        body["user"] = f"notion-task-{task_id}"
    if instructions:
        body["instructions"] = instructions

    timeout_s = _timeout()
    logger.info(
        "openclaw_client: sending request url=%s task_id=%s prompt_len=%d timeout=%ds",
        url, task_id, len(prompt), timeout_s,
    )

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
            logger.warning("openclaw_client: non-200 response: %s", error_msg)
            return {"success": False, "content": "", "error": error_msg}

        data = resp.json()
        content = _extract_text_from_response(data)
        logger.info(
            "openclaw_client: response received task_id=%s content_len=%d",
            task_id, len(content),
        )
        return {"success": True, "content": content, "raw": data}

    except httpx.TimeoutException as e:
        logger.warning("openclaw_client: timeout after %ds task_id=%s: %s", timeout_s, task_id, e)
        return {"success": False, "content": "", "error": f"timeout after {timeout_s}s"}
    except httpx.ConnectError as e:
        logger.warning("openclaw_client: connection failed task_id=%s: %s", task_id, e)
        return {"success": False, "content": "", "error": f"connection failed: {e}"}
    except Exception as e:
        logger.exception("openclaw_client: unexpected error task_id=%s", task_id)
        return {"success": False, "content": "", "error": str(e)}


def _extract_text_from_response(data: dict[str, Any]) -> str:
    """Pull the assistant's text content from the OpenResponses envelope."""
    output = data.get("output") or []
    parts: list[str] = []
    for item in output:
        if item.get("type") == "message" and item.get("role") == "assistant":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text") or "")
    if parts:
        return "\n\n".join(parts)
    # Fallback: try top-level output_text (simpler responses)
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    return ""


# ---------------------------------------------------------------------------
# Structured output format
# ---------------------------------------------------------------------------

INVESTIGATION_SECTIONS = (
    "Task Summary",
    "Root Cause",
    "Risk Level",
    "Affected Components",
    "Affected Files",
    "Recommended Fix",
    "Testing Plan",
    "Notes",
)

_STRUCTURED_OUTPUT_INSTRUCTION = (
    "\n\nIMPORTANT — format your response using exactly these markdown sections:\n\n"
    + "\n".join(f"## {s}" for s in INVESTIGATION_SECTIONS)
    + "\n\n"
    "If a section is not applicable, include the heading and write 'N/A'.\n"
    "Do not add extra top-level sections. You may use sub-headings, lists, "
    "and code blocks within each section."
)

_SECTION_HEADING_RE = re.compile(
    r"^##\s+(" + "|".join(re.escape(s) for s in INVESTIGATION_SECTIONS) + r")\s*$",
    re.MULTILINE,
)


def parse_investigation_sections(text: str) -> dict[str, str | None]:
    """Extract structured sections from an OpenClaw investigation response.

    Returns a dict keyed by section name.  Missing sections map to ``None``
    so callers can distinguish "section absent" from "section present but
    empty".  Unrecognised content before the first heading is stored under
    the key ``"_preamble"``.

    Works gracefully with older free-form reports: if *no* recognised
    headings are found the dict will contain only ``"_preamble"`` with the
    full text and every standard key set to ``None``.
    """
    result: dict[str, str | None] = {s: None for s in INVESTIGATION_SECTIONS}

    matches = list(_SECTION_HEADING_RE.finditer(text))
    if not matches:
        result["_preamble"] = text.strip() or None
        return result

    preamble = text[: matches[0].start()].strip()
    result["_preamble"] = preamble or None

    for idx, m in enumerate(matches):
        section_name = m.group(1)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        result[section_name] = body if body else None

    return result


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_WORKSPACE_NOTE = (
    "You have read-only access to the project workspace at "
    "/home/node/.openclaw/workspace/atp/. "
    "Use it to read source code, configs, docs, and scripts when investigating."
)


def _task_metadata_block(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    lines = [
        f"Task: {task.get('task', 'Untitled')}",
        f"Notion ID: {task.get('id', '')}",
        f"Type: {task.get('type', '')}",
        f"Priority: {task.get('priority', '')}",
        f"Project: {task.get('project', '')}",
        f"Details: {task.get('details', '')}",
        f"Area: {repo_area.get('area_name', '')}",
    ]
    likely = repo_area.get("likely_files") or []
    if likely:
        lines.append(f"Likely files: {', '.join(likely[:12])}")
    docs = repo_area.get("relevant_docs") or []
    if docs:
        lines.append(f"Relevant docs: {', '.join(docs[:8])}")
    runbooks = repo_area.get("relevant_runbooks") or []
    if runbooks:
        lines.append(f"Relevant runbooks: {', '.join(runbooks[:8])}")
    return "\n".join(lines)


def build_investigation_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for bug investigation tasks.

    Returns (user_prompt, system_instructions).
    """
    meta = _task_metadata_block(prepared_task)
    task = (prepared_task or {}).get("task") or {}
    symptom = (task.get("details") or task.get("task") or "").strip()

    user_prompt = (
        f"Investigate the following bug report for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Reported symptom: {symptom}\n\n"
        f"Please:\n"
        f"1. Read the relevant source files listed above to understand the current behavior.\n"
        f"2. Identify the most likely root cause.\n"
        f"3. Suggest a concrete fix (code change, config change, or operational step).\n"
        f"4. Note any risks or side effects of the fix.\n"
        f"5. Summarize your findings in the structured report format below."
        f"{_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are an expert software engineer investigating a bug in a Python/FastAPI "
        "trading platform backend with a Next.js frontend. "
        f"{_WORKSPACE_NOTE} "
        "Be thorough but concise. Focus on actionable findings. "
        "Always use the exact section headings requested in the prompt."
    )
    return user_prompt, instructions


def build_documentation_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for documentation audit/improvement tasks."""
    meta = _task_metadata_block(prepared_task)

    user_prompt = (
        f"Perform a documentation review for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Please:\n"
        f"1. Read the relevant documentation files listed above.\n"
        f"2. Identify gaps, outdated sections, or missing docs.\n"
        f"3. Suggest specific improvements or new documentation content.\n"
        f"4. Check that any referenced files/paths actually exist.\n"
        f"5. Provide your findings in the structured report format below."
        f"{_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are a technical writer auditing documentation for a trading platform. "
        f"{_WORKSPACE_NOTE} "
        "Focus on accuracy, completeness, and clarity. "
        "Reference specific file paths when suggesting changes. "
        "Always use the exact section headings requested in the prompt."
    )
    return user_prompt, instructions


def build_monitoring_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for monitoring/ops triage tasks."""
    meta = _task_metadata_block(prepared_task)

    user_prompt = (
        f"Triage the following monitoring/infrastructure issue for the "
        f"Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Please:\n"
        f"1. Read the relevant configuration and deployment files.\n"
        f"2. Identify the most likely cause of the issue.\n"
        f"3. Provide step-by-step remediation instructions.\n"
        f"4. Suggest monitoring improvements to detect this earlier.\n"
        f"5. Summarize your triage in the structured report format below."
        f"{_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are a DevOps/SRE engineer triaging an infrastructure issue. "
        "The platform runs on AWS EC2 with Docker Compose, Nginx, PostgreSQL. "
        f"{_WORKSPACE_NOTE} "
        "Be specific about commands, config changes, and file paths. "
        "Always use the exact section headings requested in the prompt."
    )
    return user_prompt, instructions


def build_generic_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for tasks that don't match specific categories."""
    meta = _task_metadata_block(prepared_task)

    user_prompt = (
        f"Analyze the following task for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Please:\n"
        f"1. Understand the task requirements by reading relevant code and docs.\n"
        f"2. Provide a thorough analysis with specific findings.\n"
        f"3. Suggest concrete next steps or solutions.\n"
        f"4. Note any risks or dependencies.\n"
        f"5. Present your analysis in the structured report format below."
        f"{_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are a senior engineer analyzing a task for a Python/FastAPI + Next.js "
        "trading platform. "
        f"{_WORKSPACE_NOTE} "
        "Be thorough, specific, and actionable. "
        "Always use the exact section headings requested in the prompt."
    )
    return user_prompt, instructions
