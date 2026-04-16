"""
Semantic matching: news articles ↔ Polymarket geopolitical markets.
Uses ONE batched FREE-tier LLM request per pipeline cycle (mandatory for rate limit compliance).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from config.settings import settings
from ingestion.gdelt_client import Article
from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)

# Maximum articles / markets to include in one batch prompt
# (balance context window vs completeness)
MAX_ARTICLES_IN_BATCH = 30
MAX_MARKETS_IN_BATCH = 50


@dataclass
class MatchedPair:
    article: Article
    market: Market
    relevance_score: float  # 0.0–1.0
    reason: str


class MarketMatcher:
    """
    Matches articles to markets via a single batched LLM call.

    IMPORTANT: Uses exactly ONE free-model request per call to match() —
    this is critical for staying within OpenRouter's 200 req/day free tier limit.
    """

    def __init__(self, router) -> None:
        self._router = router
        self._min_relevance = 0.7

    async def match(
        self,
        articles: list[Article],
        markets: list[Market],
    ) -> list[tuple[Market, list[Article]]]:
        """
        Match articles to markets.
        Returns list of (market, [relevant_articles]) tuples — one entry per market that has matches.
        Uses ONE batched LLM request for all articles + markets.
        """
        if not articles or not markets:
            logger.info("Matcher: no articles or markets — skipping")
            return []

        # Trim to limits
        articles = articles[:MAX_ARTICLES_IN_BATCH]
        markets = markets[:MAX_MARKETS_IN_BATCH]

        pairs = await self._batch_match(articles, markets)
        if not pairs:
            return []

        # Group by market
        market_map = {m.condition_id: m for m in markets}
        article_map = {str(i): a for i, a in enumerate(articles)}

        groups: dict[str, list[Article]] = {}
        for pair in pairs:
            market_id = pair.market.condition_id
            if market_id not in groups:
                groups[market_id] = []
            if pair.article not in groups[market_id]:
                groups[market_id].append(pair.article)

        result = [
            (market_map[mid], arts)
            for mid, arts in groups.items()
            if mid in market_map
        ]
        logger.info("Matcher: %d markets matched from %d articles", len(result), len(articles))
        return result

    async def _batch_match(
        self, articles: list[Article], markets: list[Market]
    ) -> list[MatchedPair]:
        """Single batched LLM request for all articles × markets."""
        prompt = self._build_batch_prompt(articles, markets)

        try:
            response_text = await self._router.call_free(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
            )
            return self._parse_response(response_text, articles, markets)
        except Exception as exc:
            logger.error("Batch matching LLM call failed: %s", exc)
            return []

    def _build_batch_prompt(self, articles: list[Article], markets: list[Market]) -> str:
        article_lines = []
        for i, art in enumerate(articles):
            article_lines.append(
                f"[A{i}] TITLE: {art.title[:150]}\n"
                f"     COUNTRY: {art.source_country} | TONE: {art.tone:.1f}"
            )

        market_lines = []
        for m in markets:
            market_lines.append(
                f"[{m.condition_id[:12]}] {m.question[:200]}"
            )

        articles_block = "\n".join(article_lines)
        markets_block = "\n".join(market_lines)

        return f"""You are a geopolitical analyst. Match news articles to prediction market questions.

ARTICLES (news from last 15 minutes):
{articles_block}

PREDICTION MARKETS (active, fee-free):
{markets_block}

For each article-market pair where the article is DIRECTLY RELEVANT to the market question:
- Include it with a relevance_score from 0.0 to 1.0
- Only include pairs with relevance_score >= 0.7
- An article is relevant if it contains information that would materially affect the probability of the market resolving YES or NO

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "matches": [
    {{
      "article_id": "A0",
      "market_id": "condition_id_prefix",
      "relevance_score": 0.85,
      "reason": "one sentence explanation"
    }}
  ]
}}

If no matches exist, return: {{"matches": []}}"""

    def _parse_response(
        self,
        response_text: str,
        articles: list[Article],
        markets: list[Market],
    ) -> list[MatchedPair]:
        # Strip markdown code fences if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Matcher response JSON parse error: %s\nResponse: %s", exc, text[:500])
            return []

        matches_raw = data.get("matches", [])
        if not isinstance(matches_raw, list):
            return []

        article_map = {f"A{i}": a for i, a in enumerate(articles)}
        # market_id in response is a prefix of condition_id
        market_map = {m.condition_id: m for m in markets}

        pairs: list[MatchedPair] = []
        for item in matches_raw:
            try:
                score = float(item.get("relevance_score", 0))
                if score < self._min_relevance:
                    continue

                article_key = str(item.get("article_id", ""))
                market_id_prefix = str(item.get("market_id", ""))

                article = article_map.get(article_key)
                # Find market by prefix match
                market = None
                for cid, m in market_map.items():
                    if cid.startswith(market_id_prefix) or market_id_prefix.startswith(cid[:12]):
                        market = m
                        break

                if article and market:
                    pairs.append(MatchedPair(
                        article=article,
                        market=market,
                        relevance_score=score,
                        reason=str(item.get("reason", "")),
                    ))
            except (ValueError, TypeError) as exc:
                logger.debug("Matcher item parse error: %s", exc)

        return pairs
