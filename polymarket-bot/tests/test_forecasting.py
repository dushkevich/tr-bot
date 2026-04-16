"""
Tests for forecasting pipeline:
- decomposer.py
- evidence_gatherer.py
- llm_forecaster.py
"""
import json
import pytest
from unittest.mock import AsyncMock


class TestDecomposer:
    async def test_returns_list_of_strings(self, mock_router, make_market):
        from forecasting.decomposer import decompose_question
        mock_router.call_free = AsyncMock(return_value='["Will X happen?", "Is Y in place?", "Does Z apply?"]')
        result = await decompose_question(make_market(), mock_router)
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(q, str) for q in result)

    async def test_caps_at_5_questions(self, mock_router, make_market):
        from forecasting.decomposer import decompose_question
        questions = [f"Question {i}?" for i in range(10)]
        mock_router.call_free = AsyncMock(return_value=json.dumps(questions))
        result = await decompose_question(make_market(), mock_router)
        assert len(result) <= 5

    async def test_returns_empty_on_parse_failure(self, mock_router, make_market):
        from forecasting.decomposer import decompose_question
        mock_router.call_free = AsyncMock(return_value="cannot parse this")
        result = await decompose_question(make_market(), mock_router)
        assert result == []

    async def test_returns_empty_on_llm_failure(self, mock_router, make_market):
        from forecasting.decomposer import decompose_question
        mock_router.call_free = AsyncMock(side_effect=RuntimeError("API error"))
        result = await decompose_question(make_market(), mock_router)
        assert result == []

    async def test_parses_markdown_wrapped_json(self, mock_router, make_market):
        from forecasting.decomposer import decompose_question
        mock_router.call_free = AsyncMock(return_value='```\n["Q1?", "Q2?"]\n```')
        result = await decompose_question(make_market(), mock_router)
        assert result == ["Q1?", "Q2?"]


class TestEvidenceGatherer:
    async def test_returns_evidence_package(self, mock_router, make_market, make_article):
        from forecasting.evidence_gatherer import gather_evidence, EvidencePackage
        articles = [make_article(title=f"News {i}") for i in range(3)]
        evidence = await gather_evidence(make_market(), articles, mock_router)
        assert isinstance(evidence, EvidencePackage)
        assert evidence.market_question
        assert evidence.article_count == 3

    async def test_empty_articles_returns_no_news_message(self, mock_router, make_market):
        from forecasting.evidence_gatherer import gather_evidence
        evidence = await gather_evidence(make_market(), [], mock_router)
        assert evidence.article_count == 0
        assert "No recent" in evidence.summarized_articles

    async def test_days_to_resolution_computed(self, mock_router, make_market, make_article):
        from forecasting.evidence_gatherer import gather_evidence
        market = make_market(resolution_date="2026-12-31")
        evidence = await gather_evidence(market, [make_article()], mock_router)
        assert evidence.days_to_resolution > 0

    async def test_news_trigger_from_first_article(self, mock_router, make_market, make_article):
        from forecasting.evidence_gatherer import gather_evidence
        art = make_article(title="Breaking: Key ceasefire talks collapse in Vienna")
        evidence = await gather_evidence(make_market(), [art], mock_router)
        assert "Breaking" in evidence.news_trigger or "ceasefire" in evidence.news_trigger


class TestLLMForecaster:
    async def test_returns_probability_in_valid_range(self, mock_router, make_market, make_article):
        from forecasting.llm_forecaster import estimate_probability
        from forecasting.evidence_gatherer import gather_evidence

        mock_router.call_paid = AsyncMock(return_value=json.dumps({
            "reasoning": "Evidence suggests high probability.",
            "sub_answers": ["Yes", "Likely"],
            "raw_probability": 0.78
        }))

        evidence = await gather_evidence(make_market(), [make_article()], mock_router)
        result = await estimate_probability(make_market(), ["Q1?"], evidence, mock_router)

        assert 0.01 <= result.raw_probability <= 0.99
        assert result.raw_probability == pytest.approx(0.78)
        assert result.reasoning

    async def test_does_not_include_market_price_in_prompt(self, mock_router, make_market, make_article):
        """CRITICAL: market price must NOT appear in the forecasting prompt."""
        from forecasting.llm_forecaster import estimate_probability, _build_forecast_prompt
        from forecasting.evidence_gatherer import gather_evidence, EvidencePackage

        market = make_market(market_price_yes=0.72)
        evidence = EvidencePackage(
            market_question=market.question,
            resolution_criteria=market.description or market.question,
            days_to_resolution=30.0,
            summarized_articles="Some news",
            base_rate_hint="",
            news_trigger="test",
        )
        prompt = _build_forecast_prompt(market, [], evidence)
        assert "0.72" not in prompt, "Market price should NOT appear in the forecasting prompt"
        assert "0.28" not in prompt, "Market price complement should NOT appear in the forecasting prompt"

    async def test_returns_neutral_on_llm_failure(self, mock_router, make_market, make_article):
        from forecasting.llm_forecaster import estimate_probability
        from forecasting.evidence_gatherer import EvidencePackage

        mock_router.call_paid = AsyncMock(side_effect=RuntimeError("Paid model down"))
        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="", base_rate_hint="", news_trigger=""
        )
        result = await estimate_probability(make_market(), [], evidence, mock_router)
        # Should return 0.5 (neutral), not crash
        assert result.raw_probability == pytest.approx(0.5)

    async def test_extracts_probability_from_malformed_response(self, mock_router, make_market):
        from forecasting.llm_forecaster import _parse_forecast_response
        response = "After careful analysis, I estimate the probability at 0.65 based on historical patterns."
        result = _parse_forecast_response(response, mock_router)
        assert result.raw_probability == pytest.approx(0.65)

    async def test_clamps_probability_to_valid_range(self, mock_router, make_market, make_article):
        from forecasting.llm_forecaster import estimate_probability
        from forecasting.evidence_gatherer import EvidencePackage

        # Model returns out-of-range value
        mock_router.call_paid = AsyncMock(return_value=json.dumps({
            "reasoning": "Very certain", "sub_answers": [], "raw_probability": 1.05
        }))
        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="", base_rate_hint="", news_trigger=""
        )
        result = await estimate_probability(make_market(), [], evidence, mock_router)
        assert result.raw_probability <= 0.99
