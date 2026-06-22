"""Read-only HostDiskFillingUp investigator (Bedrock-routed, fail-closed).

Evidence gathering uses ONLY the existing atp_ssm_runner read-only allowlist.
``docker inspect`` is intentionally excluded (it exposes container env/secrets)
and ``docker system df`` is not allowlisted, so neither is used. The model
output is advisory TEXT only; there is no code path from the recommendation to
any action.

Both flags must be explicitly enabled or this module fails closed:
JARVIS_DISK_INVESTIGATOR_ENABLED and JARVIS_BEDROCK_ENABLED.
"""

from __future__ import annotations

import logging
from typing import Callable

from app.jarvis.llm.bedrock_provider import get_bedrock_provider
from app.jarvis.llm.flags import bedrock_enabled, disk_investigator_enabled
from app.jarvis.llm.provider import LLMProvider
from app.jarvis.llm.scrub import scrub_for_llm
from app.services.atp_ssm_runner import is_command_allowed, run_atp_command

from .disk_evidence import CommandResult, DiskEvidence, DiskRecommendation

logger = logging.getLogger(__name__)

# Read-only, secret-free, allowlisted commands only.
# (docker inspect excluded to avoid env/secret exposure; docker system df is not allowlisted.)
_EVIDENCE_COMMANDS: tuple[str, ...] = (
    "df -h /",
    "free -h",
    "docker compose --profile aws ps",
)

_SYSTEM_PROMPT = (
    "You are a read-only SRE assistant. You CANNOT execute commands or make changes. "
    "Given disk evidence from a host, explain the most likely cause of the "
    "HostDiskFillingUp alert and describe remediation steps as plain advisory text only."
)

Runner = Callable[..., dict]


class DiskInvestigatorDisabled(RuntimeError):
    """Raised when the investigator runs while a required flag is off (fail-closed)."""


def gather_disk_evidence(runner: Runner = run_atp_command) -> DiskEvidence:
    """Run only allowlisted disk commands and collect their output."""
    results: list[CommandResult] = []
    for cmd in _EVIDENCE_COMMANDS:
        allowed, reason = is_command_allowed(cmd)
        if not allowed:
            # Hard guarantee: never execute a non-allowlisted command.
            logger.warning("disk_pressure: skipping non-allowlisted command %r: %s", cmd, reason)
            results.append(CommandResult(command=cmd, ok=False, status="Denied", error=f"not allowlisted: {reason}"))
            continue
        res = runner(cmd)
        results.append(
            CommandResult(
                command=cmd,
                ok=bool(res.get("ok")),
                stdout=res.get("stdout", "") or "",
                stderr=res.get("stderr", "") or "",
                status=res.get("status", "") or "",
                error=res.get("error"),
            )
        )
    return DiskEvidence(commands=results)


def build_prompt(evidence: DiskEvidence) -> str:
    """Build the (scrubbed) prompt sent to the model."""
    scrubbed = scrub_for_llm(evidence.combined_stdout())
    return (
        f"Alert: {evidence.alert}\n"
        f"Gathered at: {evidence.gathered_at}\n\n"
        f"Read-only evidence (secret-scrubbed):\n{scrubbed}\n\n"
        "Explain the likely cause and suggest remediation as advisory text only."
    )


def investigate(*, provider: LLMProvider | None = None, runner: Runner = run_atp_command) -> DiskRecommendation:
    """Produce a text-only recommendation for HostDiskFillingUp. Fail-closed."""
    if not disk_investigator_enabled():
        raise DiskInvestigatorDisabled("JARVIS_DISK_INVESTIGATOR_ENABLED is not set")
    if not bedrock_enabled():
        raise DiskInvestigatorDisabled("JARVIS_BEDROCK_ENABLED is not set")

    evidence = gather_disk_evidence(runner=runner)
    prompt = build_prompt(evidence)
    prov = provider or get_bedrock_provider()
    resp = prov.complete(prompt, system=_SYSTEM_PROMPT, max_tokens=800, temperature=0.0)

    # Advisory text only. No parsing into actions, no execution, no return of anything callable.
    return DiskRecommendation(
        alert=evidence.alert,
        summary="LLM-assisted read-only analysis of HostDiskFillingUp.",
        suggested_action=(resp.text or "").strip(),
        evidence=evidence,
        model_id=resp.model_id,
    )
