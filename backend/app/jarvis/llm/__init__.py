"""Thin LLM provider seam for JARVIS.

Bedrock-first, not Bedrock-only: agents depend on the abstract ``LLMProvider``
interface so a single model/region outage does not bind JARVIS to one vendor.
No LangChain or third-party agent framework; no OpenAI/Gemini code.
"""

from __future__ import annotations

from .flags import bedrock_enabled, disk_investigator_enabled
from .provider import LLMProvider, LLMProviderError, LLMResponse
from .scrub import scrub_for_llm

__all__ = [
    "LLMProvider",
    "LLMProviderError",
    "LLMResponse",
    "scrub_for_llm",
    "bedrock_enabled",
    "disk_investigator_enabled",
]
