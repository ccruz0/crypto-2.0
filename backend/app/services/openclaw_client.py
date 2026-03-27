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
# Model chain and cheap-first policy (see docs/OPENCLAW_LOW_COST_MODEL_FALLBACK_STRATEGY.md)
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "openclaw"
_FALLBACK_DELAY_S = 2


def _model_chain() -> list[str]:
    """Ordered list of models to try (``OPENCLAW_MODEL_CHAIN`` or PRIMARY + FALLBACK_*).

    Operators should order the chain cheap→expensive for cost control. ``OPENCLAW_CHEAP_FIRST_MODE``
    does **not** reorder models; it is logged only (see ``_cheap_first_mode``).
    """
    chain_raw = (os.environ.get("OPENCLAW_MODEL_CHAIN") or "").strip()
    if chain_raw:
        return [m.strip() for m in chain_raw.split(",") if m.strip()]
    primary = (os.environ.get("OPENCLAW_PRIMARY_MODEL") or "").strip() or _DEFAULT_MODEL
    chain = [primary]
    for i in range(1, 6):
        fallback = (os.environ.get(f"OPENCLAW_FALLBACK_MODEL_{i}") or "").strip()
        if fallback:
            chain.append(fallback)
    return chain


def _cheap_first_mode() -> bool:
    """Telemetry only: reflects ``OPENCLAW_CHEAP_FIRST_MODE`` for logs. Does not change routing."""
    raw = (os.environ.get("OPENCLAW_CHEAP_FIRST_MODE") or "true").strip().lower()
    return raw in ("1", "true", "yes")


def _verification_model_chain() -> list[str] | None:
    """Model chain for solution verification only. If set, verification uses this (cheaper) chain instead of main.
    Returns None when unset so caller uses main chain."""
    chain_raw = (os.environ.get("OPENCLAW_VERIFICATION_MODEL_CHAIN") or "").strip()
    if chain_raw:
        return [m.strip() for m in chain_raw.split(",") if m.strip()]
    primary = (os.environ.get("OPENCLAW_VERIFICATION_PRIMARY_MODEL") or "").strip()
    if primary:
        return [primary]
    return None


def _verification_max_chars() -> int:
    """Max chars of generated output to send to verification (cost control). Default 8000."""
    raw = (os.environ.get("OPENCLAW_VERIFICATION_MAX_CHARS") or "").strip()
    if raw:
        try:
            n = int(raw)
            return max(500, min(n, 50000))
        except ValueError:
            pass
    return 8000


def _task_details_max_chars() -> int:
    """Max chars for task details/symptom in prompts. Default 8000."""
    raw = (os.environ.get("OPENCLAW_TASK_DETAILS_MAX_CHARS") or "").strip()
    if raw:
        try:
            n = int(raw)
            return max(500, min(n, 50000))
        except ValueError:
            pass
    return 8000


def _truncate_task_text(text: str, *, max_chars: int | None = None) -> str:
    """Truncate long Notion task text for prompts (cost control)."""
    m = max_chars if max_chars is not None else _task_details_max_chars()
    t = (text or "").strip()
    if len(t) <= m:
        return t
    return t[:m] + "\n…(truncated)"


def _optional_max_output_tokens() -> int | None:
    """If ``OPENCLAW_MAX_OUTPUT_TOKENS`` is set to a positive int, pass through to the gateway."""
    raw = (os.environ.get("OPENCLAW_MAX_OUTPUT_TOKENS") or "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
        if n <= 0:
            return None
        return min(n, 128_000)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Task-type model routing: cheap chain for doc/monitoring, main for bug/complex
# ---------------------------------------------------------------------------

def _cheap_task_types() -> set[str]:
    """Task types that use the cheap model chain. From OPENCLAW_CHEAP_TASK_TYPES (comma-separated)."""
    raw = (os.environ.get("OPENCLAW_CHEAP_TASK_TYPES") or "").strip().lower()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def _cheap_task_model_chain() -> list[str] | None:
    """Model chain for lightweight task types (doc, monitoring). If set, apply uses this for matching tasks."""
    chain_raw = (os.environ.get("OPENCLAW_CHEAP_MODEL_CHAIN") or "").strip()
    if chain_raw:
        return [m.strip() for m in chain_raw.split(",") if m.strip()]
    primary = (os.environ.get("OPENCLAW_CHEAP_PRIMARY_MODEL") or "").strip()
    if primary:
        return [primary]
    return None


def get_apply_model_chain_override(
    prepared_task: dict[str, Any],
    save_subdir: str,
) -> list[str] | None:
    """If cheap chain is configured and the task matches, return it; else None.

    - ``OPENCLAW_CHEAP_TASK_TYPES`` non-empty: match Notion task ``type`` (case-insensitive), or
      match ``save_subdir`` containing ``generated-notes`` or ``triage``.
    - ``OPENCLAW_CHEAP_TASK_TYPES`` empty: match **only** by ``save_subdir`` (``generated-notes`` /
      ``triage``), so operators can rely on path routing with ``OPENCLAW_CHEAP_MODEL_CHAIN`` alone.
    - ``bug-investigations`` never uses the cheap chain.
    """
    chain = _cheap_task_model_chain()
    if not chain:
        return None

    if "bug-investigations" in save_subdir:
        return None

    types = _cheap_task_types()
    task = (prepared_task or {}).get("task") or {}
    task_type = str(task.get("type") or "").strip().lower()
    subdir_cheap = "generated-notes" in save_subdir or "triage" in save_subdir

    if types:
        if task_type and task_type in types:
            return chain
        if subdir_cheap:
            return chain
        return None

    if subdir_cheap:
        return chain
    return None


def _is_failover_condition(result: dict[str, Any]) -> bool:
    """True if the result indicates we should try the next model (rate limit, credit, 5xx, timeout, etc.)."""
    if result.get("success"):
        return False
    err = (result.get("error") or "").lower()
    if "429" in err or "rate limit" in err or "too many requests" in err:
        return True
    if "402" in err or "payment required" in err or "insufficient credit" in err or "quota exceeded" in err or "low balance" in err:
        return True
    if "timeout" in err or "connection failed" in err or "connection refused" in err:
        return True
    if any(x in err for x in ("500", "502", "503", "504", "503 ", "502 ")):
        return True
    if "model not available" in err or "model not found" in err or "model not supported" in err:
        return True
    if "unavailable" in err or "service unavailable" in err:
        return True
    return False


def _post_one(
    prompt: str,
    model: str,
    *,
    task_id: str = "",
    instructions: str | None = None,
) -> dict[str, Any]:
    """Single POST to OpenClaw with the given model. Returns result dict with optional status_code for non-200."""
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
        "model": model,
        "input": prompt,
    }
    if task_id:
        body["user"] = f"notion-task-{task_id}"
    if instructions:
        body["instructions"] = instructions
    _max_out = _optional_max_output_tokens()
    if _max_out is not None:
        body["max_output_tokens"] = _max_out

    timeout_s = _timeout()
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
            out = {"success": False, "content": "", "error": error_msg, "status_code": resp.status_code}
            logger.warning("openclaw_client: non-200 model=%s status=%s task_id=%s", model, resp.status_code, task_id)
            return out

        data = resp.json()
        content = _extract_text_from_response(data)
        out: dict[str, Any] = {"success": True, "content": content, "raw": data}
        usage = _extract_usage(data)
        if usage:
            out["usage"] = usage
        return out

    except httpx.TimeoutException as e:
        logger.warning("openclaw_client: timeout model=%s after %ds task_id=%s: %s", model, timeout_s, task_id, e)
        return {"success": False, "content": "", "error": f"timeout after {timeout_s}s"}
    except httpx.ConnectError as e:
        logger.warning("openclaw_client: connection failed model=%s task_id=%s: %s", model, task_id, e)
        return {"success": False, "content": "", "error": f"connection failed: {e}"}
    except Exception as e:
        logger.exception("openclaw_client: unexpected error model=%s task_id=%s", model, task_id)
        return {"success": False, "content": "", "error": str(e)}


# ---------------------------------------------------------------------------
# Core HTTP call (with model fallback)
# ---------------------------------------------------------------------------

def send_to_openclaw(
    prompt: str,
    *,
    task_id: str = "",
    instructions: str | None = None,
    model_chain_override: list[str] | None = None,
) -> dict[str, Any]:
    """Send a prompt to OpenClaw with model fallback. Tries each model in the configured chain until success or exhausted.

    When model_chain_override is provided (e.g. verification chain), that list is used instead of the default chain.

    Returns ``{"success": True, "content": "...", "raw": {...}, "model_used": "...", "usage": {...}}`` on success
    (usage optional if gateway provides it), or ``{"success": False, "content": "", "error": "..."}`` on failure.
    """
    import time as _time
    chain = model_chain_override if model_chain_override is not None else _model_chain()
    if not chain:
        chain = [_DEFAULT_MODEL]

    primary = chain[0]
    logger.info(
        "openclaw_client: primary_model=%s task_id=%s prompt_len=%d cheap_first=%s",
        primary, task_id, len(prompt), _cheap_first_mode(),
    )

    last_result: dict[str, Any] = {"success": False, "content": "", "error": "no models tried"}
    for idx, model in enumerate(chain):
        result = _post_one(prompt, model, task_id=task_id, instructions=instructions)
        if result.get("success"):
            result["model_used"] = model
            usage = result.get("usage")
            if idx > 0:
                logger.info(
                    "openclaw_client: fallback_succeeded model_used=%s task_id=%s escalation_used=true%s",
                    model, task_id, f" usage={usage}" if usage else "",
                )
            else:
                logger.info(
                    "openclaw_client: response received task_id=%s content_len=%d model=%s%s",
                    task_id, len(result.get("content") or ""), model,
                    f" usage={usage}" if usage else "",
                )
            return result

        last_result = result
        if _is_failover_condition(result) and idx < len(chain) - 1:
            next_model = chain[idx + 1]
            logger.warning(
                "openclaw_client: failover reason=%s model_tried=%s next_model=%s task_id=%s",
                (result.get("error") or "unknown")[:200], model, next_model, task_id,
            )
            _time.sleep(_FALLBACK_DELAY_S)
            continue
        break

    return last_result


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


def _extract_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract token usage from gateway response if present. Returns dict with input_tokens, output_tokens, total_tokens (when available)."""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if key in usage and isinstance(usage[key], (int, float)):
            out[key] = int(usage[key])
    return out if out else None


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

_INVESTIGATION_MIN_SECTIONS_INSTRUCTION = (
    "\n\nMANDATORY minimum sections (must all be present exactly):\n"
    "## Summary\n"
    "## Root Cause\n"
    "## Fix\n"
    "## Next Steps\n\n"
    "Do NOT return short answers.\n"
    "Do NOT return a single sentence.\n"
    "Output must be at least 300 characters."
)

_SECTION_HEADING_RE = re.compile(
    r"^##\s+(" + "|".join(re.escape(s) for s in INVESTIGATION_SECTIONS) + r")\s*$",
    re.MULTILINE,
)

# Multi-agent shared output schema (docs/agents/multi-agent/SHARED_OUTPUT_SCHEMA.md)
AGENT_OUTPUT_SECTIONS = (
    "Issue Summary",
    "Scope Reviewed",
    "Confirmed Facts",
    "Mismatches",
    "Root Cause",
    "Proposed Minimal Fix",
    "Risk Level",
    "Validation Plan",
    "Cursor Patch Prompt",
)

_AGENT_STRUCTURED_OUTPUT_INSTRUCTION = (
    "\n\nIMPORTANT — format your response using exactly these markdown sections:\n\n"
    + "\n".join(f"## {s}" for s in AGENT_OUTPUT_SECTIONS)
    + "\n\n"
    "If a section is not applicable, include the heading and write 'N/A'.\n"
    "Do not add extra top-level sections. Be precise and cite file paths."
)

_AGENT_SECTION_HEADING_RE = re.compile(
    r"^##\s+(" + "|".join(re.escape(s) for s in AGENT_OUTPUT_SECTIONS) + r")\s*$",
    re.MULTILINE,
)


def parse_all_markdown_sections(text: str) -> dict[str, str]:
    """Extract ALL ## Section Name -> content from markdown. Canonical parser for .sections.json.

    Use this at artifact creation time to ensure .sections.json is always complete.
    Handles frontmatter (---...---) and trailing ---. Returns dict with _preamble and
    all ## sections. Empty/N/A section bodies are omitted.
    """
    result: dict[str, str] = {}
    parts = text.split("---")
    if len(parts) >= 3:
        body = parts[2].strip()  # YAML frontmatter: ---...---\ncontent
    elif len(parts) == 2:
        # Single ---: pick the part with more ## sections (main content vs header/footer)
        body = max(parts, key=lambda p: p.count("\n## ")).strip()
    else:
        body = (parts[0] if parts else "").strip()
    if not body:
        return result
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    if matches:
        preamble = body[: matches[0].start()].strip()
        if preamble:
            result["_preamble"] = preamble
    for idx, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if content and name.lower() not in ("", "n/a"):
            result[name] = content
    return result


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


def parse_agent_output_sections(text: str) -> dict[str, str | None]:
    """Extract structured sections from a multi-agent operator response.

    Returns dict keyed by AGENT_OUTPUT_SECTIONS. Missing sections map to None.
    Unrecognised content before first heading stored under "_preamble".
    """
    result: dict[str, str | None] = {s: None for s in AGENT_OUTPUT_SECTIONS}

    matches = list(_AGENT_SECTION_HEADING_RE.finditer(text))
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
    "Use it to read source code, configs, docs, and scripts when investigating. "
    "IMPORTANT: Never read a directory path directly (causes EISDIR error). "
    "Always list a directory first, then read the specific files inside it."
)

_ATP_COMMAND_NOTE = (
    "CRITICAL: Runtime context (docker ps, logs) is PRE-FETCHED and included in the prompt below. "
    "NEVER run docker, sudo, or shell commands locally — you have no such capability and it will fail. "
    "Use ONLY the pre-fetched context and workspace file reads. Do NOT suggest manual SSH or local commands."
)

# Strict mode: hard override for investigation tasks — blocks ready-for-patch until proof exists
_STRICT_MODE_BLOCK = """
## STRICT MODE ENABLED

You must NOT:
- auto-complete
- skip investigation steps
- reuse previous conclusions without proof
- propose a fix before proving the exact failure point

You must:
- identify exact failure point with file, function, line or condition
- include code-level evidence
- provide one concrete failing scenario
- trace the data flow end to end
- continue investigating if proof is incomplete

The task is NOT complete unless proof is present.

---
"""


def _execution_mode_from_prepared_task(prepared_task: dict[str, Any]) -> str:
    """Read execution_mode from prepared_task. Default 'normal' when absent."""
    mode = (prepared_task or {}).get("execution_mode")
    if mode is not None and isinstance(mode, str):
        v = mode.strip().lower()
        if v == "strict":
            return "strict"
    task = (prepared_task or {}).get("task") or {}
    mode = task.get("execution_mode")
    if mode is not None and isinstance(mode, str):
        v = mode.strip().lower()
        if v == "strict":
            return "strict"
    return "normal"


def prepend_strict_mode_if_needed(user_prompt: str, prepared_task: dict[str, Any]) -> str:
    """If execution_mode is strict, prepend the strict mode block to user_prompt."""
    if _execution_mode_from_prepared_task(prepared_task) != "strict":
        return user_prompt
    return _STRICT_MODE_BLOCK + user_prompt


def validate_strict_mode_proof(content: str) -> tuple[bool, str]:
    """Validate that content contains minimum proof criteria for strict mode ready-for-patch.

    ALL of the following are REQUIRED:
    (a) At least one real file path (with slash: backend/, app/, path/to/file.ext)
    (b) At least one real function definition (def name / async def name / function name)
    (c) At least one code block (```...``` with code-like content)
    (d) Explicit root cause that references code (root cause phrase near file/function)
    (e) Explicit failing scenario (repro / steps to reproduce / failing scenario)
    (f) Explicit fix logic (fix phrase + action: add, change, replace, check, etc.)
    (g) Explicit validation scenarios (how to verify: validate, verify, test, confirm)

    Rejects: generic explanation, no concrete code refs, no reproduction, no fix explanation.
    Returns (passed: bool, reason: str).
    """
    if not content or len(content.strip()) < 100:
        return False, "content too short for proof validation"

    text = content.lower()
    missing: list[str] = []

    # (a) Real file path: must contain slash (repo path) or backend/app/frontend prefix
    real_file_patterns = (
        r"(?:backend|frontend|app)/[^\s]+\.(?:py|ts|tsx)\b",
        r"[^\s]+/[^\s]+\.(?:py|ts|tsx)\b",  # path/to/file.py
    )
    has_file = any(re.search(p, content, re.I) for p in real_file_patterns)
    if not has_file:
        missing.append("at least one real file path (e.g. backend/.../file.py)")

    # (b) Real function definition: def name, async def name, or function name
    has_func = bool(re.search(r"\b(def|async\s+def)\s+\w+\s*\(", content, re.I))
    if not has_func:
        has_func = bool(re.search(r"\bfunction\s+\w+\s*\(", content, re.I))
    if not has_func:
        missing.append("at least one real function definition (def name(...) or function name(...))")

    # (c) Code block: ```...``` with code-like content (assignment, call, def, return, etc.)
    code_block_match = re.search(r"```[\s\S]+?```", content)
    has_snippet = False
    if code_block_match:
        block = code_block_match.group(0)
        code_like = any(
            re.search(r, block)
            for r in (
                r"[=\(\)\[\]\{\}]",  # brackets/assign
                r"\b(def|return|if|for|import)\b",
                r"\w+\s*\(",  # function call
            )
        )
        has_snippet = code_like
    if not has_snippet:
        missing.append("at least one code block with code-like content")

    # (d) Root cause explicitly referencing code: root cause phrase and file/function nearby
    has_root_cause_phrase = any(
        k in text for k in ("root cause", "rootcause", "cause:", "caused by")
    )
    if not has_root_cause_phrase:
        missing.append("explicit root cause classification")
    else:
        # Reject generic/hedged root cause
        if re.search(r"root\s+cause\s+(?:might|could|possibly|may)\b", text):
            missing.append("root cause must be stated definitively (not 'might/could')")
        else:
            # Require root cause to reference code: file or function within ~300 chars of "root cause" / "caused by"
            root_idx = min(
                (text.find(k) for k in ("root cause", "rootcause", "caused by") if k in text),
                default=len(text),
            )
            window = content[max(0, root_idx - 150) : root_idx + 350]
            refs_code = (
                any(re.search(p, window, re.I) for p in real_file_patterns)
                or bool(re.search(r"\b(def|async\s+def|function)\s+\w+", window, re.I))
            )
            if not refs_code:
                missing.append("root cause must reference code (file path or function name)")

    # (e) Explicit failing scenario
    has_scenario = any(
        k in text
        for k in (
            "reproduce",
            "repro steps",
            "steps to reproduce",
            "failing scenario",
            "reproduction",
            "minimal repro",
            "when user",
            "when the user",
            "concrete scenario",
        )
    )
    if not has_scenario:
        missing.append("explicit failing scenario (repro steps / failing scenario / when user...)")

    # (f) Explicit fix logic: fix phrase + action verb
    has_fix_phrase = any(
        k in text
        for k in (
            "recommended fix",
            "proposed fix",
            "proposed minimal",
            "minimal fix",
            "fix:",
            "solution",
            "rationale",
        )
    )
    has_fix_action = any(
        k in text for k in ("add ", "change ", "replace ", "check ", "update ", "ensure ", "handle ", "fix ")
    )
    if not has_fix_phrase:
        missing.append("explicit fix section (recommended fix / proposed fix / fix:)")
    elif not has_fix_action:
        missing.append("explicit fix logic (add/change/replace/check/ensure/handle)")

    # (g) Explicit validation scenarios
    has_validation = any(
        k in text
        for k in (
            "validat",
            "verify",
            "regression",
            "confirm",
            "check that",
            "manual test",
            "automated test",
            "how to verify",
            "how to test",
        )
    )
    if not has_validation:
        missing.append("explicit validation scenarios (verify / test / confirm / how to verify)")

    # Line/condition: still require some location or condition
    has_line = bool(
        re.search(r"(?:line\s+\d+|L\d+|:\d+|at\s+line|line\s*\d+)", content, re.I)
        or "condition" in text
    )
    if not has_line:
        missing.append("line/condition reference (line N, L123, or condition)")

    # Anti-pattern: generic explanation without substance
    generic_phrases = (
        "investigate further",
        "consider checking the logs",
        "might be in the backend",
        "could be related to",
    )
    if any(g in text for g in generic_phrases) and (not has_file or not has_snippet):
        missing.append("concrete code references required (no generic 'investigate further')")

    if missing:
        return False, "strict mode proof incomplete: missing " + "; ".join(missing)
    return True, "proof criteria satisfied"


def _fetch_atp_runtime_context() -> str:
    """Fetch PROD and LAB runtime context via safe SSM APIs. Injected into prompts so OpenClaw
    never needs to run docker/sudo locally. Returns a markdown block or empty string on failure."""
    blocks: list[str] = []
    try:
        from app.services.atp_ssm_runner import run_atp_command
        r = run_atp_command("docker compose --profile aws ps")
        if r.get("ok"):
            out = (r.get("stdout") or "").strip()[:2500]
            blocks.append("### ATP PROD (docker compose --profile aws ps)\n```\n" + out + "\n```")
        else:
            err = (r.get("error") or "unknown")[:200]
            blocks.append("### ATP PROD: unavailable (" + err + ")")
    except Exception as e:
        logger.debug("atp_runtime_context: atp fetch failed: %s", e)
        blocks.append("### ATP PROD: fetch failed")
    try:
        from app.services.lab_ssm_runner import run_lab_command
        r = run_lab_command("docker ps")
        if r.get("ok"):
            out = (r.get("stdout") or "").strip()[:1500]
            blocks.append("### LAB (docker ps)\n```\n" + out + "\n```")
        else:
            err = (r.get("error") or "unknown")[:200]
            blocks.append("### LAB: unavailable (" + err + ")")
    except Exception as e:
        logger.debug("atp_runtime_context: lab fetch failed: %s", e)
        blocks.append("### LAB: fetch failed")
    if not blocks:
        return ""
    return "## Pre-fetched runtime context (do NOT run docker/sudo — use this)\n\n" + "\n\n".join(blocks)


def _task_metadata_block(prepared_task: dict[str, Any], *, retry_mode: bool = False) -> str:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    details_raw = str(task.get("details") or "")
    details_line = _truncate_task_text(details_raw)
    lines = [
        f"Task: {task.get('task', 'Untitled')}",
        f"Notion ID: {task.get('id', '')}",
        f"Type: {task.get('type', '')}",
        f"Priority: {task.get('priority', '')}",
        f"Project: {task.get('project', '')}",
        f"Details: {details_line}",
        f"Area: {repo_area.get('area_name', '')}",
    ]
    likely = repo_area.get("likely_files") or []
    if retry_mode:
        if likely:
            lines.append(f"Previously identified files (reuse only): {', '.join(likely[:8])}")
    else:
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
    retry_mode = bool((prepared_task or {}).get("_investigation_retry_mode"))
    meta = _task_metadata_block(prepared_task, retry_mode=retry_mode)
    task = (prepared_task or {}).get("task") or {}
    symptom = _truncate_task_text((task.get("details") or task.get("task") or "").strip())
    runtime = _fetch_atp_runtime_context()

    user_prompt = ""
    if runtime:
        user_prompt = f"{runtime}\n\n---\n\n"
    retry_mode_block = (
        "RETRY INVESTIGATION MODE (MANDATORY):\n"
        "- Do NOT output orientation/preparation checklists.\n"
        "- Do NOT output 'OpenClaw preparation plan'.\n"
        "- Do NOT repeat instructions like 'read docs', 'check runbooks', or 'inspect likely files'.\n"
        "- Use prior failure feedback and previously identified files only.\n"
        "- Respond directly with code-grounded investigation evidence.\n\n"
        if retry_mode
        else ""
    )
    step1_line = (
        "1. Use prior failure feedback to produce a stronger code-grounded investigation.\n"
        if retry_mode
        else "1. Read the relevant source files listed above to understand the current behavior.\n"
    )
    user_prompt += (
        f"Investigate the following bug report for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Reported symptom: {symptom}\n\n"
        f"{retry_mode_block}"
        f"HARD OUTPUT REQUIREMENTS (MANDATORY):\n"
        f"- Root cause MUST reference a real file path and a real function name.\n"
        f"- Failing scenario MUST be explicit and reproducible (e.g., when user sends..., when scheduler runs...).\n"
        f"- Code reference MUST include:\n"
        f"  1) at least one real function definition, and\n"
        f"  2) at least one code block.\n"
        f"- Generic preparation plans are invalid (examples: 'read docs', 'check runbooks', 'investigate further').\n"
        f"- If concrete code evidence is missing, the output is invalid.\n\n"
        f"Required minimal format (example):\n"
        f"Root cause:\n"
        f"In backend/app/services/telegram_commands.py inside _handle_task_command()\n\n"
        f"Failing scenario:\n"
        f"When user sends /task twice quickly...\n\n"
        f"Code reference:\n"
        f"```python\n"
        f"def _handle_task_command(...):\n"
        f"    ...\n"
        f"```\n\n"
        f"Please:\n"
        f"{step1_line}"
        f"2. Identify the most likely root cause.\n"
        f"3. Suggest a concrete fix (code change, config change, or operational step).\n"
        f"4. Note any risks or side effects of the fix.\n"
        f"5. Summarize your findings in the structured report format below."
        f"{_STRUCTURED_OUTPUT_INSTRUCTION}"
        f"{_INVESTIGATION_MIN_SECTIONS_INSTRUCTION}"
    )
    instructions = (
        "You are an expert software engineer investigating a bug in a Python/FastAPI "
        "trading platform backend with a Next.js frontend. "
        f"{_WORKSPACE_NOTE} "
        f"{_ATP_COMMAND_NOTE} "
        "Be thorough but concise. Focus on actionable findings. "
        "Do not output generic plans or checklists. "
        "Every conclusion must be tied to real code evidence. "
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
    runtime = _fetch_atp_runtime_context()

    user_prompt = ""
    if runtime:
        user_prompt = f"{runtime}\n\n---\n\n"
    user_prompt += (
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
        f"{_ATP_COMMAND_NOTE} "
        "Be specific about commands, config changes, and file paths. "
        "Always use the exact section headings requested in the prompt."
    )
    return user_prompt, instructions


def build_telegram_alerts_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for Telegram and Alerts agent (multi-agent operator)."""
    meta = _task_metadata_block(prepared_task)
    task = (prepared_task or {}).get("task") or {}
    symptom = _truncate_task_text((task.get("details") or task.get("task") or "").strip())
    runtime = _fetch_atp_runtime_context()

    user_prompt = ""
    if runtime:
        user_prompt = f"{runtime}\n\n---\n\n"
    user_prompt += (
        f"Investigate the following Telegram/alert issue for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Reported symptom: {symptom}\n\n"
        f"Scope (read these files):\n"
        f"- backend/app/services/telegram_notifier.py\n"
        f"- backend/app/services/telegram_commands.py\n"
        f"- backend/app/services/alert_emitter.py\n"
        f"- backend/app/services/signal_throttle.py\n"
        f"- docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md\n\n"
        f"Check for:\n"
        f"1. RUN_TELEGRAM, ENVIRONMENT, TELEGRAM_CHAT_ID resolution (never log values)\n"
        f"2. Kill switch blocking sends\n"
        f"3. Throttle/dedup: repeated alerts, missing alerts, approval noise\n"
        f"4. Docs vs code mismatches (runbook outdated?)\n"
        f"5. Wrong channel (trading vs ops chat_id)\n\n"
        f"Typical issues: alerts not sent, duplicate alerts, throttle too aggressive, "
        f"TELEGRAM_CHAT_ID misconfiguration.\n\n"
        f"Propose the smallest safe fix. Use the exact section headings below."
        f"{_AGENT_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are the Telegram and Alerts agent. You analyze alert delivery, throttle, dedup, kill switch, and channel config. "
        "You do NOT change production send logic without explicit approval. "
        "Never log or expose tokens. "
        f"{_WORKSPACE_NOTE} "
        f"{_ATP_COMMAND_NOTE} "
        "Cite exact file paths and env var names (not values). "
        "Cursor Patch Prompt must be safe (no credential changes). "
        "All 9 sections are mandatory; use N/A only when truly not applicable."
    )
    return user_prompt, instructions


def build_execution_state_prompt(prepared_task: dict[str, Any]) -> tuple[str, str]:
    """Build prompt for Execution and State agent (multi-agent operator)."""
    meta = _task_metadata_block(prepared_task)
    task = (prepared_task or {}).get("task") or {}
    symptom = _truncate_task_text((task.get("details") or task.get("task") or "").strip())
    runtime = _fetch_atp_runtime_context()

    user_prompt = ""
    if runtime:
        user_prompt = f"{runtime}\n\n---\n\n"
    user_prompt += (
        f"Investigate the following order/execution/state issue for the Automated Trading Platform.\n\n"
        f"{meta}\n\n"
        f"Reported symptom: {symptom}\n\n"
        f"Scope (read these files):\n"
        f"- backend/app/services/exchange_sync.py\n"
        f"- backend/app/services/signal_monitor.py (order creation, lifecycle)\n"
        f"- backend/app/services/brokers/crypto_com_trade.py\n"
        f"- backend/app/models/exchange_order.py\n"
        f"- docs/ORDER_LIFECYCLE_GUIDE.md, docs/SYSTEM_MAP.md, docs/LIFECYCLE_EVENTS_COMPLETE.md\n\n"
        f"Check for:\n"
        f"1. CRITICAL: 'Order not in open orders' does NOT mean canceled. Resolve via exchange order_history/trade_history only.\n"
        f"2. Exchange vs DB vs dashboard mismatches (state reconciliation)\n"
        f"3. Lifecycle state issues: EXECUTED vs CANCELED confusion, SL/TP order lifecycle\n"
        f"4. Sync messages misleading or stale\n"
        f"5. Rendering/state reconciliation in dashboard\n\n"
        f"Typical issues: order not found, missing from open orders, DB vs exchange mismatch, "
        f"dashboard showing wrong state, lifecycle event ordering.\n\n"
        f"Propose minimal fix. Do NOT change order placement logic. Use the exact section headings below."
        f"{_AGENT_STRUCTURED_OUTPUT_INSTRUCTION}"
    )
    instructions = (
        "You are the Execution and State agent. You analyze order lifecycle, sync, state consistency, and exchange/DB/dashboard reconciliation. "
        "You do NOT place or cancel orders. Never assume missing from open orders = canceled; use exchange history only. "
        f"{_WORKSPACE_NOTE} "
        f"{_ATP_COMMAND_NOTE} "
        "Cite exchange API behavior and code paths. "
        "Cursor Patch Prompt must not change order execution. "
        "All 9 sections are mandatory; use N/A only when truly not applicable."
    )
    return user_prompt, instructions


# ---------------------------------------------------------------------------
# Solution verification (does output address the task requirements?)
# ---------------------------------------------------------------------------

_VERIFY_INSTRUCTIONS = (
    "You are a strict reviewer. Your job is to determine if the generated output "
    "actually addresses the problem stated in the task. "
    "Answer ONLY with one of these two lines:\n"
    "VERDICT: PASS\n"
    "REASON: <brief reason>\n\n"
    "OR\n\n"
    "VERDICT: FAIL\n"
    "REASON: <brief reason explaining what is missing or wrong>\n\n"
    "Be strict: PASS only if the output clearly addresses the task requirements. "
    "FAIL if the output is generic, off-topic, or does not solve the stated problem."
)


def verify_solution_against_task(
    task_title: str,
    task_details: str,
    generated_output: str,
    *,
    task_id: str = "",
    previous_feedback: str | None = None,
) -> tuple[bool, str]:
    """Ask OpenClaw if the generated output addresses the task requirements.

    Returns (passed: bool, reason: str).
    On API failure, returns (False, "verification unavailable: <error>").
    """
    if not is_openclaw_configured():
        return False, "verification unavailable: OpenClaw not configured"

    feedback_block = ""
    if previous_feedback:
        previous_feedback = previous_feedback[:400]
        feedback_block = (
            f"\n\nPrevious verification feedback (the output failed this check):\n"
            f"{previous_feedback}\n\n"
            "The author has been asked to improve. Re-evaluate the new output."
        )

    max_chars = _verification_max_chars()
    title_v = _truncate_task_text(str(task_title), max_chars=2000)
    details_v = _truncate_task_text(str(task_details))
    prompt = (
        f"TASK:\n"
        f"Title: {title_v}\n"
        f"Details: {details_v}\n\n"
        f"GENERATED OUTPUT:\n"
        f"---\n{generated_output[:max_chars]}\n---\n\n"
        f"Does this output address the problem stated in the task?{feedback_block}"
    )

    verification_chain = _verification_model_chain()
    result = send_to_openclaw(
        prompt,
        task_id=task_id or "verify",
        instructions=_VERIFY_INSTRUCTIONS,
        model_chain_override=verification_chain,
    )

    if not result.get("success"):
        return False, f"verification unavailable: {result.get('error', 'unknown')}"

    content = (result.get("content") or "").strip().upper()
    if "VERDICT: PASS" in content:
        reason = ""
        for line in content.split("\n"):
            if line.startswith("REASON:"):
                reason = line[7:].strip()
                break
        return True, reason or "verified"
    if "VERDICT: FAIL" in content:
        reason = ""
        for line in content.split("\n"):
            if line.startswith("REASON:"):
                reason = line[7:].strip()
                break
        return False, reason or "output does not address task requirements"

    # Unclear response - treat as fail to be safe
    return False, f"verification unclear: {content[:200]}"


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
