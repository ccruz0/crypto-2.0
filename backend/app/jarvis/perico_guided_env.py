"""Apply in-process env changes from operator-guided Perico mission input lines."""

from __future__ import annotations

import os
import re

# Machine lines stripped before the planner sees the operator body (keeps LLM context clean).
_PERICO_ENV_SET = re.compile(r"^\s*\[PERICO_ENV\s+([A-Z0-9_]+)=([^\]]+?)\]\s*$", re.IGNORECASE)
_PERICO_ENV_CLEAR = re.compile(r"^\s*\[PERICO_ENV\s+CLEAR\s+([A-Z0-9_]+)\]\s*$", re.IGNORECASE)


def apply_perico_guided_env_from_input(text: str) -> tuple[str, list[str]]:
    """
    Parse ``[PERICO_ENV KEY=value]`` and ``[PERICO_ENV CLEAR KEY]`` lines, apply to ``os.environ``,
    and return ``(remaining_text_for_planner, applied_labels)``.
    """
    applied: list[str] = []
    out_lines: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _PERICO_ENV_SET.match(s)
        if m:
            key, val = m.group(1).upper(), m.group(2).strip()
            if key == "PERICO_REPO_ROOT":
                os.environ[key] = val
                applied.append(f"{key}={val}")
            continue
        m2 = _PERICO_ENV_CLEAR.match(s)
        if m2:
            key = m2.group(1).upper()
            os.environ.pop(key, None)
            applied.append(f"{key}=<unset>")
            continue
        out_lines.append(line)
    return "\n".join(out_lines).strip(), applied
