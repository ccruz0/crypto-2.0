"""Config-driven Bedrock model router with a Converse-probe startup preflight.

Rationale (R6, point 2): the outage happened because tier->model IDs were
hardcoded literals with nothing validating them, so an EOL/invalid ID only
surfaced as a live production failure. This module moves the mapping into
external config and adds a preflight that validates every configured ID at
startup, turning the next EOL into a deploy-time error instead of an outage.

Preflight design (per client constraint): a catalog listing is *not* sufficient
-- a profile can be ACTIVE in ``list-inference-profiles`` while Converse still
rejects it (EOL, or an account-wide "Operation not allowed"). So the preflight
issues a real minimal Converse call per configured ID and classifies the result.
It draws a hard line between two very different failures:

  * an **invalid/EOL/not-found** ID is a *config bug* -- preflight raises
    ``ModelConfigError`` naming the tier, so a bad deploy is caught before serving;
  * an account-wide **"Operation not allowed"** block is *not* the config's fault
    and is transient (pending AWS enabling model access), so it is reported and
    counted but does not, by itself, fail the preflight -- the same config passes
    once access is enabled.

The Converse prober is injected, so this module is fully unit-testable offline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.jarvis import failure_metrics
from app.jarvis.bedrock_client import classify_bedrock_error

logger = logging.getLogger(__name__)

VALID_TIERS = ("simple", "standard", "critical")
_PLACEHOLDER_PREFIX = "REPLACE_WITH_"

# Preflight per-tier outcome classes.
STATUS_OK = "ok"
STATUS_MODEL_INVALID = "model_invalid"            # EOL / not-found / validation -> config bug
STATUS_ACCOUNT_RESTRICTED = "account_restricted"  # "Operation not allowed" -> transient, account-side
STATUS_IAM_DENIED = "iam_denied"                  # permissions -> environment bug
STATUS_ERROR = "error"                            # anything else

# Failure classes that mean "this configured ID is unusable" -> preflight fails.
_HARD_CONFIG_FAILURES = {STATUS_MODEL_INVALID, STATUS_IAM_DENIED, STATUS_ERROR}


class ModelConfigError(RuntimeError):
    """The model config is missing, malformed, or references unusable IDs."""


@dataclass(frozen=True)
class TierProbe:
    """Result of probing one tier's configured model."""

    tier: str
    model_id: str
    status: str
    detail: str = ""


def load_model_config(path: str | Path) -> dict[str, Any]:
    """Load and structurally validate the tier->model config.

    Raises :class:`ModelConfigError` if the file is missing, not valid JSON,
    missing a tier, or still contains placeholder IDs.
    """
    p = Path(path)
    if not p.is_file():
        raise ModelConfigError(f"model config not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ModelConfigError(f"model config is not valid JSON: {e}") from e

    tiers = data.get("tiers")
    if not isinstance(tiers, dict):
        raise ModelConfigError("model config missing 'tiers' object")

    missing = [t for t in VALID_TIERS if t not in tiers]
    if missing:
        raise ModelConfigError(f"model config missing tier(s): {', '.join(missing)}")

    placeholders = []
    for tier in VALID_TIERS:
        model_id = _tier_id(tiers, tier)
        if not model_id:
            raise ModelConfigError(f"tier '{tier}' has no 'id'")
        if model_id.startswith(_PLACEHOLDER_PREFIX):
            placeholders.append(tier)
    if placeholders:
        raise ModelConfigError(
            "model config still has placeholder IDs for tier(s): "
            f"{', '.join(placeholders)} -- fill from `aws bedrock list-inference-profiles`"
        )
    return data


def _tier_id(tiers: dict[str, Any], tier: str) -> str:
    entry = tiers.get(tier)
    if isinstance(entry, dict):
        return str(entry.get("id") or "").strip()
    return str(entry or "").strip()


class ModelRouter:
    """Resolves a task tier to a configured Bedrock model/profile ID."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._region = str(config.get("region") or "").strip()
        tiers = config["tiers"]
        self._by_tier = {t: _tier_id(tiers, t) for t in VALID_TIERS}

    @property
    def region(self) -> str:
        return self._region

    def resolve(self, tier: str) -> str:
        """Return the model/profile ID for ``tier``.

        Raises :class:`ModelConfigError` for an unknown tier -- a caller asking for
        a tier that doesn't exist is a bug, not a silent default.
        """
        if tier not in self._by_tier:
            raise ModelConfigError(
                f"unknown tier '{tier}'; valid tiers: {', '.join(VALID_TIERS)}"
            )
        return self._by_tier[tier]

    def configured_ids(self) -> set[str]:
        return set(self._by_tier.values())

    def preflight(
        self,
        prober: Callable[[str], None],
        *,
        catalog: Iterable[str] | None = None,
    ) -> dict[str, TierProbe]:
        """Validate every configured ID with a real Converse probe.

        ``prober(model_id)`` must attempt a minimal Converse call and return
        ``None`` on success or raise on failure. ``catalog``, if given, is a cheap
        pre-check (the listed IDs) so an ID that isn't even listed is caught as
        ``model_invalid`` without spending a Converse call.

        Returns a per-tier :class:`TierProbe` map for visibility/logging. Raises
        :class:`ModelConfigError` if any tier is a hard config failure
        (invalid/EOL ID, IAM denial, or unclassified error). An account-wide
        restriction ("Operation not allowed") is *reported and counted* but does
        not raise -- the same config will pass once AWS enables access.
        """
        catalog_set = {str(x).strip() for x in catalog} if catalog is not None else None
        results: dict[str, TierProbe] = {}

        for tier, model_id in self._by_tier.items():
            if catalog_set is not None and model_id not in catalog_set:
                results[tier] = TierProbe(
                    tier, model_id, STATUS_MODEL_INVALID, "not present in account catalog"
                )
                continue
            try:
                prober(model_id)
                results[tier] = TierProbe(tier, model_id, STATUS_OK)
            except Exception as e:  # noqa: BLE001 -- classify every failure shape
                status = _status_from_exc(e)
                results[tier] = TierProbe(tier, model_id, status, str(e))

        self._report(results)

        hard = {t: r for t, r in results.items() if r.status in _HARD_CONFIG_FAILURES}
        if hard:
            detail = "; ".join(
                f"{t}={r.model_id} [{r.status}]" for t, r in sorted(hard.items())
            )
            raise ModelConfigError(
                f"preflight failed -- {len(hard)} tier(s) reference unusable model IDs: {detail}"
            )
        return results

    def _report(self, results: dict[str, TierProbe]) -> None:
        for r in results.values():
            if r.status == STATUS_OK:
                logger.info("preflight tier=%s model=%s OK", r.tier, r.model_id)
            elif r.status == STATUS_ACCOUNT_RESTRICTED:
                # Not a config fault, but operators must see it -- count + ERROR.
                failure_metrics.record_invocation_failure("account_restriction")
                logger.error(
                    "preflight tier=%s model=%s ACCOUNT RESTRICTED (Operation not allowed) -- "
                    "config is valid; awaiting AWS model access",
                    r.tier,
                    r.model_id,
                )
            else:
                logger.error(
                    "preflight tier=%s model=%s %s: %s",
                    r.tier,
                    r.model_id,
                    r.status.upper(),
                    r.detail,
                )


def _status_from_exc(exc: BaseException) -> str:
    kind = classify_bedrock_error(exc)
    return {
        "account_restriction": STATUS_ACCOUNT_RESTRICTED,
        "iam_denied": STATUS_IAM_DENIED,
        "model_not_found": STATUS_MODEL_INVALID,
        "request_failed": STATUS_ERROR,
    }.get(kind, STATUS_ERROR)


def default_converse_prober(region: str) -> Callable[[str], None]:
    """Build a prober that issues a minimal real Converse call for ``region``.

    Kept out of :meth:`ModelRouter.preflight` so the router stays offline-testable;
    the boto3 import is lazy so importing this module never requires AWS. A
    ``maxTokens`` of 1 keeps the probe as cheap as a Converse call can be.
    """

    def _probe(model_id: str) -> None:
        import boto3  # noqa: PLC0415 -- lazy so tests/imports don't need AWS

        client = boto3.client("bedrock-runtime", region_name=region)
        client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            inferenceConfig={"maxTokens": 1},
        )

    return _probe


def default_inference_profile_lister(region: str) -> Callable[[], list[str]]:
    """Build a lister enumerating inference profiles via boto3 for ``region``.

    Useful as the cheap ``catalog`` pre-check argument to :meth:`ModelRouter.preflight`.
    """

    def _list() -> list[str]:
        import boto3  # noqa: PLC0415 -- lazy so tests/imports don't need AWS

        client = boto3.client("bedrock", region_name=region)
        ids: list[str] = []
        for item in client.list_inference_profiles().get("inferenceProfileSummaries", []):
            pid = item.get("inferenceProfileId")
            if pid:
                ids.append(pid)
        return ids

    return _list
