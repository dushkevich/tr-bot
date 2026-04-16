"""
Tests for ingestion/matcher.py
- Batch enforcement (one request per cycle)
- Correct JSON parsing
- Relevance threshold filtering
- Empty article/market handling
"""
import json
import pytest
from unittest.mock import AsyncMock

from ingestion.matcher import MarketMatcher, MAX_ARTICLES_IN_BATCH, MAX_MARKETS_IN_BATCH


@pytest.fixture
def matcher(mock_router):
    return MarketMatcher(router=mock_router)


class TestBatchEnforcement:
    async def test_single_llm_call_regardless_of_market_count(
        self, matcher, mock_router, make_market, make_article
    ):
        """Critical: match() must use exactly ONE LLM call per invocation."""
        articles = [make_article(title=f"News {i}") for i in range(10)]
        markets = [make_market(condition_id=f"mkt-{i:03d}") for i in range(20)]

        # Return empty matches
        mock_router.call_free = AsyncMock(return_value='{"matches": []}')
        await matcher.match(articles, markets)

        assert mock_router.call_free.call_count == 1, (
            "match() must make exactly ONE free-model call regardless of article/market count"
        )

    async def test_respects_article_batch_limit(
        self, matcher, mock_router, make_article, make_market
    ):
        """Articles beyond MAX_ARTICLES_IN_BATCH should be silently dropped."""
        articles = [make_article(title=f"News {i}") for i in range(MAX_ARTICLES_IN_BATCH + 20)]
        markets = [make_market()]
        mock_router.call_free = AsyncMock(return_value='{"matches": []}')
        await matcher.match(articles, markets)
        # Should still only call once, not multiple batches
        assert mock_router.call_free.call_count == 1


class TestResponseParsing:
    async def test_valid_match_returned(
        self, matcher, mock_router, make_article, make_market
    ):
        market = make_market(condition_id="abc123def456")
        article = make_article()
        response = json.dumps({
            "matches": [
                {
                    "article_id": "A0",
                    "market_id": "abc123def4",  # prefix of condition_id
                    "relevance_score": 0.85,
                    "reason": "Directly relevant to ceasefire"
                }
            ]
        })
        mock_router.call_free = AsyncMock(return_value=response)

        result = await matcher.match([article], [market])
        assert len(result) == 1
        matched_market, matched_articles = result[0]
        assert matched_market.condition_id == "abc123def456"
        assert article in matched_articles

    async def test_low_relevance_filtered_out(
        self, matcher, mock_router, make_article, make_market
    ):
        """Scores below 0.7 should not produce matches."""
        market = make_market(condition_id="abc123")
        article = make_article()
        response = json.dumps({
            "matches": [{"article_id": "A0", "market_id": "abc123", "relevance_score": 0.5, "reason": "weak"}]
        })
        mock_router.call_free = AsyncMock(return_value=response)
        result = await matcher.match([article], [market])
        assert len(result) == 0

    async def test_malformed_json_returns_empty(
        self, matcher, mock_router, make_article, make_market
    ):
        mock_router.call_free = AsyncMock(return_value="not valid json {{{")
        result = await matcher.match([make_article()], [make_market()])
        assert result == []

    async def test_markdown_wrapped_json_parsed(
        self, matcher, mock_router, make_article, make_market
    ):
        """Model sometimes wraps JSON in markdown fences — should still parse."""
        market = make_market(condition_id="xyz999abc")
        response = '```json\n{"matches": [{"article_id": "A0", "market_id": "xyz999", "relevance_score": 0.9, "reason": "ok"}]}\n```'
        mock_router.call_free = AsyncMock(return_value=response)
        result = await matcher.match([make_article()], [market])
        assert len(result) == 1


class TestEdgeCases:
    async def test_empty_articles_returns_empty(self, matcher, mock_router, make_market):
        result = await matcher.match([], [make_market()])
        assert result == []
        mock_router.call_free.assert_not_called()

    async def test_empty_markets_returns_empty(self, matcher, mock_router, make_article):
        result = await matcher.match([make_article()], [])
        assert result == []
        mock_router.call_free.assert_not_called()

    async def test_llm_failure_returns_empty(self, matcher, mock_router, make_article, make_market):
        mock_router.call_free = AsyncMock(side_effect=RuntimeError("API down"))
        result = await matcher.match([make_article()], [make_market()])
        assert result == []

    async def test_multiple_articles_same_market_grouped(
        self, matcher, mock_router, make_article, make_market
    ):
        """Multiple articles matching the same market should group under one market entry."""
        market = make_market(condition_id="group-test")
        arts = [make_article(title=f"Article {i}") for i in range(3)]
        response = json.dumps({
            "matches": [
                {"article_id": "A0", "market_id": "group-te", "relevance_score": 0.9, "reason": "a"},
                {"article_id": "A1", "market_id": "group-te", "relevance_score": 0.8, "reason": "b"},
                {"article_id": "A2", "market_id": "group-te", "relevance_score": 0.75, "reason": "c"},
            ]
        })
        mock_router.call_free = AsyncMock(return_value=response)
        result = await matcher.match(arts, [market])
        assert len(result) == 1
        _, matched_arts = result[0]
        assert len(matched_arts) == 3
