"""The ONE place the AI price used for cost estimates lives (MBA ops panel, docs/mba-ops.md).

``mbaAiUsage`` stores only a call count per student per day (tutor hints, mock analyst,
GDPI feedback share it), not tokens, so the ops panel ESTIMATES cost as
``calls x typical tokens per call x price``. Every number is an env override:

* ``MBA_AI_PRICE_INPUT_PER_MTOK_USD`` / ``MBA_AI_PRICE_OUTPUT_PER_MTOK_USD`` — USD per 1M tokens.
  Defaults are OpenAI's public standard-tier price for the default model gpt-4o-mini
  ($0.15 input / $0.60 output; https://developers.openai.com/api/docs/pricing, retrieved
  2026-11-13). Update both when ``OPENAI_MODEL`` changes.
* ``MBA_AI_EST_INPUT_TOKENS`` / ``MBA_AI_EST_OUTPUT_TOKENS`` — assumed tokens per call
  (prompt with question + passage + solution; reply capped at 200-900 tokens).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "gpt-4o-mini"
PRICE_SOURCE_URL = "https://developers.openai.com/api/docs/pricing"


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass(frozen=True)
class AiPricing:
    model: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    est_input_tokens: float
    est_output_tokens: float
    source_url: str = PRICE_SOURCE_URL

    @property
    def per_call_usd(self) -> float:
        return (self.est_input_tokens * self.input_per_mtok_usd + self.est_output_tokens * self.output_per_mtok_usd) / 1_000_000

    def cost_usd(self, calls: int) -> float:
        return round(calls * self.per_call_usd, 4)


def ai_pricing() -> AiPricing:
    return AiPricing(
        model=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
        input_per_mtok_usd=_float("MBA_AI_PRICE_INPUT_PER_MTOK_USD", 0.15),
        output_per_mtok_usd=_float("MBA_AI_PRICE_OUTPUT_PER_MTOK_USD", 0.60),
        est_input_tokens=_float("MBA_AI_EST_INPUT_TOKENS", 1500),
        est_output_tokens=_float("MBA_AI_EST_OUTPUT_TOKENS", 500),
    )
