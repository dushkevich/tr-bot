"""
Frontier model probability estimator [PAID model].
Implements SuperForecaster methodology — does NOT include market price in prompt.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from forecasting.evidence_gatherer import EvidencePackage
from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    raw_probability: float          # Model's raw probability estimate (0.0–1.0)
    reasoning: str                  # Full reasoning chain
    sub_answers: list[str] = field(default_factory=list)
    model_name: str = ""


async def estimate_probability(
    market: Market,
    sub_questions: list[str],
    evidence: EvidencePackage,
    router,
) -> ForecastResult:
    """
    Query the frontier (PAID) model for a calibrated probability estimate.
    CRITICAL: market price is NOT included in the prompt to prevent anchoring bias.
    """
    prompt = _build_forecast_prompt(market, sub_questions, evidence)

    try:
        response = await router.call_paid(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert superforecaster with a track record of calibrated "
                        "probabilistic reasoning. You give precise numerical probabilities, "
                        "not vague qualitative assessments. You are aware of base rates, "
                        "reference class forecasting, and common cognitive biases."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
        )
        return _parse_forecast_response(response, router)
    except Exception as exc:
        logger.error("Paid model forecast failed for %s: %s", market.condition_id, exc)
        # Return a neutral estimate rather than crashing the pipeline
        return ForecastResult(
            raw_probability=0.5,
            reasoning=f"Forecast failed: {exc}",
        )


def _build_forecast_prompt(
    market: Market,
    sub_questions: list[str],
    evidence: EvidencePackage,
) -> str:
    sub_q_text = ""
    if sub_questions:
        sub_q_text = "\n\nSUB-QUESTIONS TO ANSWER:\n" + "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(sub_questions)
        )

    base_rate_text = ""
    if evidence.base_rate_hint:
        base_rate_text = f"\n\nBASE RATE CONTEXT:\n{evidence.base_rate_hint}"

    time_text = ""
    if evidence.days_to_resolution > 0:
        time_text = f"\n\nTIME CONTEXT:\n{evidence.days_to_resolution:.0f} days until resolution deadline."

    return f"""PREDICTION MARKET QUESTION:
{market.question}

RESOLUTION CRITERIA:
{evidence.resolution_criteria}
{sub_q_text}

RECENT NEWS EVIDENCE:
{evidence.summarized_articles}
{base_rate_text}
{time_text}

INSTRUCTIONS:
1. Answer each sub-question above with a brief assessment.
2. Synthesize all evidence to estimate the probability this market resolves YES.
3. Apply reference class thinking: what is the base rate for this type of event?
4. Avoid anchoring or availability bias.
5. Give a calibrated probability — not just high/low.

Return ONLY valid JSON (no markdown):
{{
  "sub_answers": ["answer to sub-q 1", "answer to sub-q 2", ...],
  "reasoning": "your full reasoning chain (2-4 paragraphs)",
  "raw_probability": 0.XX
}}

The raw_probability must be a decimal between 0.01 and 0.99. Do not include the market price in your reasoning."""


def _parse_forecast_response(response: str, router) -> ForecastResult:
    text = response.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    # Try direct parse
    try:
        data = json.loads(text)
        prob = float(data.get("raw_probability", 0.5))
        prob = max(0.01, min(0.99, prob))
        return ForecastResult(
            raw_probability=prob,
            reasoning=str(data.get("reasoning", "")),
            sub_answers=[str(s) for s in data.get("sub_answers", [])],
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Try extracting JSON object from mixed text
    match = re.search(r"\{[^{}]*\"raw_probability\"[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            prob = float(data.get("raw_probability", 0.5))
            prob = max(0.01, min(0.99, prob))
            return ForecastResult(
                raw_probability=prob,
                reasoning=str(data.get("reasoning", text[:500])),
                sub_answers=[str(s) for s in data.get("sub_answers", [])],
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Last resort: extract a decimal probability from text
    prob_match = re.search(r"\b0\.\d{2,}\b", text)
    if prob_match:
        prob = float(prob_match.group())
        if 0.01 <= prob <= 0.99:
            logger.warning("Extracted probability from unstructured response: %.2f", prob)
            return ForecastResult(raw_probability=prob, reasoning=text[:1000])

    logger.error("Could not parse forecast response: %s", text[:500])
    return ForecastResult(raw_probability=0.5, reasoning="Parse failure — using neutral 0.5")
