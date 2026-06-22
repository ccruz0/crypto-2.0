"""Scrub env-like / secret content before any text is sent to an LLM.

Defense-in-depth: even though the disk investigator only gathers non-secret,
allowlisted command output, every prompt is passed through ``scrub_for_llm``
first so an accidental secret can never leave the host via the model call.
"""

from __future__ import annotations

import re

REDACTION = "[REDACTED]"

# KEY=VALUE / export KEY=VALUE (uppercase env-style keys). Value is fully redacted.
_ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?)([A-Z][A-Z0-9_]{2,})(\s*=\s*)(.+)$")
# Concrete credential value shapes, redacted even when not in KEY=VALUE form.
_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
_BEARERISH = re.compile(r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def scrub_for_llm(text: str) -> str:
    """Return ``text`` with env-assignments and obvious credential values redacted."""
    if not text:
        return text or ""

    text = _PEM.sub(REDACTION, text)

    out: list[str] = []
    for line in text.splitlines():
        m = _ASSIGNMENT.match(line)
        if m:
            out.append(f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTION}")
            continue
        line = _AWS_ACCESS_KEY.sub(REDACTION, line)
        line = _BEARERISH.sub(REDACTION, line)
        out.append(line)
    return "\n".join(out)
