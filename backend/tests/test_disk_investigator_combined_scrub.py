"""Combined-evidence scrub boundary tests for the disk investigator.

These prove ``scrub_for_llm`` covers the FULL assembled ``DiskEvidence``
(df + free + docker compose ps), not just the first command, and that
redaction is order-independent: a secret planted in ANY of the three command
slots is redacted in the combined prompt.

No real Bedrock and no real SSM: the provider and runner are injected fakes.
Secret values are constructed at runtime (concatenation) so no literal
credential shape is ever committed to source or appears in ``git diff``.
"""

from __future__ import annotations

from app.jarvis.investigations.investigators import disk_pressure as dp
from app.jarvis.investigations.investigators.disk_evidence import (
    CommandResult,
    DiskEvidence,
)
from app.jarvis.llm.provider import LLMResponse

# Synthetic, NON-real credential shapes built at runtime so the literal
# strings never land in committed source. Each matches a scrub rule:
#   _AWS_SECRET -> value of an env-assignment (KEY=VALUE redaction)
#   _GHP_TOKEN  -> inline GitHub PAT shape (_BEARERISH redaction)
#   _DB_PASS    -> value of an env-assignment (KEY=VALUE redaction)
_AWS_SECRET = "wJalr" + "X" * 35
_GHP_TOKEN = "ghp_" + "b" * 36
_DB_PASS = "p4ss" + "w0rd" * 4

_PLANTED = (_AWS_SECRET, _GHP_TOKEN, _DB_PASS)


class _CapturingProvider:
    def __init__(self) -> None:
        self.last_prompt: str | None = None

    def complete(self, prompt, *, system=None, max_tokens=1024, temperature=0.0):
        self.last_prompt = prompt
        return LLMResponse(text="advisory text only", model_id="m-test")


def _df_clean() -> str:
    return "Filesystem Size Used Avail Use% Mounted on\n/dev/root 49G 47G 2G 96% /"


def _free_clean() -> str:
    return "              total        used        free\nMem:           1.9Gi       1.6Gi       0.1Gi"


def _secret_block() -> str:
    """A command output carrying MULTIPLE planted secret shapes."""
    return (
        "NAME STATUS\n"
        "backend Up\n"
        f"AWS_SECRET_ACCESS_KEY={_AWS_SECRET}\n"
        f"runner token {_GHP_TOKEN} active\n"
        f"DATABASE_PASSWORD={_DB_PASS}"
    )


def _evidence(outputs: list[str]) -> DiskEvidence:
    return DiskEvidence(
        commands=[
            CommandResult(command=cmd, ok=True, stdout=out, status="Success")
            for cmd, out in zip(dp._EVIDENCE_COMMANDS, outputs)
        ]
    )


def _assert_no_secrets(text: str) -> None:
    for secret in _PLANTED:
        assert secret not in text, "a planted secret value leaked into the prompt"


def test_combined_evidence_scrubs_secret_planted_in_third_command():
    # Secret lives ONLY in the THIRD (docker compose ps) command output. The
    # first scrub test only proved the first command was covered; this proves
    # the combined assembly is covered.
    evidence = _evidence([_df_clean(), _free_clean(), _secret_block()])
    prompt = dp.build_prompt(evidence)

    _assert_no_secrets(prompt)
    # Clean evidence still survives (we redact secrets, not everything).
    assert "/dev/root" in prompt
    assert "[REDACTED]" in prompt


def test_combined_evidence_scrubbed_in_text_handed_to_provider(monkeypatch):
    # End-to-end through investigate(): the final prompt string handed to the
    # provider must contain NONE of the planted secret values.
    monkeypatch.setenv("JARVIS_DISK_INVESTIGATOR_ENABLED", "true")
    monkeypatch.setenv("JARVIS_BEDROCK_ENABLED", "true")

    def runner(cmd: str, **_kwargs) -> dict:
        out = {
            "df -h /": _df_clean(),
            "free -h": _free_clean(),
            "docker compose --profile aws ps": _secret_block(),
        }.get(cmd, "")
        return {"ok": True, "stdout": out, "stderr": "", "status": "Success", "error": None}

    provider = _CapturingProvider()
    dp.investigate(provider=provider, runner=runner)

    assert provider.last_prompt is not None
    _assert_no_secrets(provider.last_prompt)


def test_scrub_is_order_independent_across_all_three_slots():
    # Plant the secret block in each command slot in turn; it must be redacted
    # regardless of which command carried it.
    for idx in range(len(dp._EVIDENCE_COMMANDS)):
        outputs = [_df_clean(), _free_clean(), _df_clean()]
        outputs[idx] = _secret_block()
        prompt = dp.build_prompt(_evidence(outputs))
        _assert_no_secrets(prompt)
