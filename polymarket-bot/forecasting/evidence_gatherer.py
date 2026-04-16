"""
Evidence gatherer: compiles evidence package for LLM context [FREE model].
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ingestion.gdelt_client import Article
from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)

MAX_EVIDENCE_TOKENS = 1000  # approx characters × 0.75


@dataclass
class EvidencePackage:
    market_question: str
    resolution_criteria: str
    days_to_resolution: float
    summarized_articles: str        # LLM-compressed article summaries
    base_rate_hint: str             # historical frequency if known
    article_count: int = 0
    news_trigger: str = ""          # one-line summary of what triggered analysis


async def gather_evidence(
    market: Market,
    articles: list[Article],
    router,
) -> EvidencePackage:
    """
    Build an evidence package for a given market + matched articles.
    Compresses article content to fit within token budget.
    """
    days_to_resolution = _compute_days_to_resolution(market.resolution_date)

    if not articles:
        return EvidencePackage(
            market_question=market.question,
            resolution_criteria=market.description or market.question,
            days_to_resolution=days_to_resolution,
            summarized_articles="No recent news articles found.",
            base_rate_hint="",
            article_count=0,
            news_trigger="No recent news.",
        )

    summarized, news_trigger = await _summarize_articles(articles, market, router)

    return EvidencePackage(
        market_question=market.question,
        resolution_criteria=market.description or market.question,
        days_to_resolution=days_to_resolution,
        summarized_articles=summarized,
        base_rate_hint=_estimate_base_rate(market),
        article_count=len(articles),
        news_trigger=news_trigger,
    )


async def _summarize_articles(
    articles: list[Article],
    market: Market,
    router,
) -> tuple[str, str]:
    """Compress articles into a token-budget-respecting summary."""
    # First try a simple truncation approach (no LLM call needed if small)
    raw_text = "\n\n".join(
        f"[{art.source_country}] {art.title}" + (f"\n{art.summary[:200]}" if art.summary else "")
        for art in articles[:10]
    )

    if len(raw_text) <= MAX_EVIDENCE_TOKENS * 4:
        # Small enough — no LLM summarization needed
        news_trigger = articles[0].title[:150] if articles else "No news"
        return raw_text[:MAX_EVIDENCE_TOKENS * 4], news_trigger

    # Need LLM compression
    articles_text = "\n".join(
        f"- [{art.source_country}] {art.title}"
        for art in articles[:20]
    )

    prompt = f"""Summarize the following news articles in relation to this prediction market question.
Focus only on information relevant to the outcome.
Keep your summary under 300 words.

MARKET QUESTION: {market.question}

NEWS ARTICLES:
{articles_text}

Return ONLY the summary text, no preamble."""

    try:
        summary = await router.call_free(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        news_trigger = articles[0].title[:150] if articles else "No news"
        return summary.strip(), news_trigger
    except Exception as exc:
        logger.warning("Evidence summarization failed: %s", exc)
        # Fallback: first 3 headlines
        trigger = articles[0].title[:150] if articles else "No news"
        return "\n".join(art.title for art in articles[:3]), trigger


def _compute_days_to_resolution(resolution_date: str) -> float:
    if not resolution_date:
        return 30.0
    try:
        dt = datetime.fromisoformat(resolution_date.replace("Z", "+00:00"))
        # If the parsed datetime has no timezone, treat it as UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (dt - now).total_seconds() / 86400
        return max(0.0, delta)
    except (ValueError, TypeError):
        return 30.0


def _estimate_base_rate(market: Market) -> str:
    """
    Rough base rate hints based on market type.
    In Phase 2 this could be backed by actual GKG historical data.
    """
    question_lower = market.question.lower()

    if "ceasefire" in question_lower:
        return "Historical base rate: ceasefires in active conflicts occur ~20-30% of the time within any given month."
    if "election" in question_lower and "win" in question_lower:
        return "Historical base rate: incumbents win re-election ~60% of the time in democratic systems."
    if "sanction" in question_lower:
        return "Historical base rate: new sanctions imposed on country ~40-60% of the time when diplomatically tense."
    if "resign" in question_lower or "resign" in question_lower:
        return "Historical base rate: sitting leaders resign under pressure ~15-25% of the time when scandals emerge."

    return ""
