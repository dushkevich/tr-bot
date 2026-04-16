"""
Shared fixtures for all tests.
Provides mock DB, mock LLM router, mock markets, mock articles.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Event loop fixture (pytest-asyncio)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Mock market + article factories
# ---------------------------------------------------------------------------

@pytest.fixture
def make_market():
    from ingestion.market_fetcher import Market

    def _make(
        condition_id: str = "test-001",
        question: str = "Will there be a ceasefire by end of month?",
        market_price_yes: float = 0.72,
        divergence_target: float = 0.0,
        **kwargs,
    ) -> Market:
        return Market(
            condition_id=condition_id,
            event_id="event-001",
            question=question,
            category="Geopolitics",
            market_price_yes=market_price_yes,
            market_price_no=1.0 - market_price_yes,
            volume=50_000,
            liquidity=15_000,
            neg_risk=False,
            fees_enabled=False,
            accepting_orders=True,
            resolution_date="2026-06-01",
            **kwargs,
        )
    return _make


@pytest.fixture
def make_article():
    from ingestion.gdelt_client import Article

    def _make(
        title: str = "Conflict talks resume in Geneva",
        tone: float = -2.5,
        source_country: str = "US",
        **kwargs,
    ) -> Article:
        return Article(
            article_id=f"http://example.com/{title[:10]}",
            url=f"http://example.com/{title[:10]}",
            title=title,
            source_country=source_country,
            tone=tone,
            themes=["CRISISLEX_CRISISLEXREC", "MILITARY"],
            published_at="2026-04-11T10:00:00Z",
            **kwargs,
        )
    return _make


# ---------------------------------------------------------------------------
# Mock model router
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_router():
    router = AsyncMock()

    # Default free response: valid JSON match result
    router.call_free = AsyncMock(return_value='{"matches": []}')

    # Default paid response: valid forecast JSON
    router.call_paid = AsyncMock(return_value=(
        '{"reasoning": "Based on evidence...", '
        '"sub_answers": ["Yes, likely"], '
        '"raw_probability": 0.78}'
    ))
    return router


# ---------------------------------------------------------------------------
# Mock DB (in-memory, no aiosqlite)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db(tmp_path, monkeypatch):
    """
    Patches dashboard.db to use a real SQLite in a temp directory.
    Avoids polluting the real DB during tests.
    """
    import dashboard.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    return db_module


@pytest.fixture
async def initialized_db(mock_db):
    await mock_db.init_db()
    return mock_db


# ---------------------------------------------------------------------------
# Sample calibration data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_calibration_data():
    """25 synthetic (prediction, outcome) pairs for Platt Scaling tests."""
    import random
    random.seed(42)
    data = []
    for _ in range(25):
        pred = random.uniform(0.3, 0.9)
        # Slightly noisy: outcome correlates with prediction
        outcome = 1 if random.random() < pred else 0
        data.append((pred, outcome))
    return data


# ---------------------------------------------------------------------------
# Mock risk state
# ---------------------------------------------------------------------------

@pytest.fixture
def healthy_risk_state():
    return {
        "id": 1,
        "daily_pnl": 0.0,
        "total_exposure": 100.0,
        "open_position_count": 2,
        "current_balance": 450.0,
        "kill_switch_active": False,
        "last_updated": "2026-04-11T10:00:00Z",
    }
