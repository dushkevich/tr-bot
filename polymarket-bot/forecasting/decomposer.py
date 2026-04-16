"""
Question decomposer: breaks binary market questions into 3–5 sub-questions [FREE model].
"""
from __future__ import annotations

import json
import logging

from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)


async def decompose_question(market: Market, router) -> list[str]:
    """
    Decompose a binary market question into 3–5 sub-questions.
    Returns the sub-questions as a list of strings.
    Falls back to an empty list on failure (pipeline continues without decomposition).
    """
    prompt = f"""You are a superforecaster. Break down this prediction market question into 3-5 fundamental sub-questions.

MARKET QUESTION: {market.question}
RESOLUTION DATE: {market.resolution_date}
DESCRIPTION: {market.description[:500] if market.description else 'N/A'}

The sub-questions should be:
1. More specific and answerable than the original
2. Together sufficient to determine whether the market resolves YES or NO
3. Based on verifiable facts or events

Return ONLY a JSON array of strings. No markdown, no explanation.
Example: ["Will X happen before Y?", "Does Z have the authority to do W?", ...]"""

    try:
        response = await router.call_free(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        return _parse_sub_questions(response)
    except Exception as exc:
        logger.warning("Decomposition failed for %s: %s", market.condition_id, exc)
        return []


def _parse_sub_questions(response: str) -> list[str]:
    text = response.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        questions = json.loads(text)
        if isinstance(questions, list):
            return [str(q) for q in questions if q][:5]
    except json.JSONDecodeError:
        # Try to extract a JSON array if wrapped in other text
        import re
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if match:
            try:
                questions = json.loads(match.group())
                return [str(q) for q in questions if q][:5]
            except json.JSONDecodeError:
                pass

    logger.debug("Could not parse sub-questions from: %s", text[:200])
    return []
