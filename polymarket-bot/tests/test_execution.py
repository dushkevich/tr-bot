"""
Tests for execution layer:
- DRY_RUN mode: signal recorded to DB, no real CLOB call
- Position size capping
- Signal generator Kelly math
- Convergence scanner
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Signal generator tests
# ---------------------------------------------------------------------------

class TestSignalGenerator:
    async def test_records_signal_even_when_below_threshold(self, make_market, initialized_db):
        from signals.signal_generator import generate_signal
        from forecasting.evidence_gatherer import EvidencePackage

        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="news", base_rate_hint="", news_trigger="trigger",
        )
        market = make_market(market_price_yes=0.72)

        # Calibrated estimate close to market price — below threshold
        signal = await generate_signal(
            market=market,
            calibrated_estimate=0.74,  # only 2% divergence — below 8% threshold
            raw_estimates={"paid_model": 0.74},
            evidence=evidence,
        )

        assert signal is None  # Not tradeable

        # But signal should still be in DB
        signals = await initialized_db.get_recent_signals(n=5)
        assert len(signals) == 1
        assert signals[0]["action"] == "BELOW_THRESHOLD"

    async def test_returns_signal_when_above_threshold(self, make_market, initialized_db):
        from signals.signal_generator import generate_signal
        from forecasting.evidence_gatherer import EvidencePackage

        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="news", base_rate_hint="", news_trigger="trigger",
        )
        market = make_market(market_price_yes=0.65)

        signal = await generate_signal(
            market=market,
            calibrated_estimate=0.80,  # 15% divergence — above 8% threshold
            raw_estimates={"paid_model": 0.80},
            evidence=evidence,
        )

        assert signal is not None
        assert signal.side == "YES"  # Model says higher → BUY YES
        assert signal.divergence == pytest.approx(0.15, abs=0.01)

    async def test_buys_no_when_model_below_market(self, make_market, initialized_db):
        from signals.signal_generator import generate_signal
        from forecasting.evidence_gatherer import EvidencePackage

        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="news", base_rate_hint="", news_trigger="trigger",
        )
        market = make_market(market_price_yes=0.75)

        signal = await generate_signal(
            market=market,
            calibrated_estimate=0.55,  # Model says lower → BUY NO
            raw_estimates={"paid_model": 0.55},
            evidence=evidence,
        )

        assert signal is not None
        assert signal.side == "NO"

    async def test_position_size_capped_at_max(self, make_market, initialized_db):
        from signals.signal_generator import generate_signal
        from forecasting.evidence_gatherer import EvidencePackage
        from config.settings import settings

        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="news", base_rate_hint="", news_trigger="trigger",
        )

        signal = await generate_signal(
            market=make_market(market_price_yes=0.65),
            calibrated_estimate=0.99,  # Huge divergence → large Kelly → must be capped
            raw_estimates={"paid_model": 0.99},
            evidence=evidence,
        )

        if signal:
            assert signal.size_usdc <= settings.trading.max_trade_size_usdc

    async def test_outside_trading_zone_not_traded(self, make_market, initialized_db):
        from signals.signal_generator import generate_signal
        from forecasting.evidence_gatherer import EvidencePackage

        evidence = EvidencePackage(
            market_question="Q?", resolution_criteria="R", days_to_resolution=30,
            summarized_articles="news", base_rate_hint="", news_trigger="trigger",
        )
        # Market price outside trading zone (60–80%) but in pre-filter zone
        market = make_market(market_price_yes=0.57)

        signal = await generate_signal(
            market=market,
            calibrated_estimate=0.80,  # 23% divergence but price outside trading zone
            raw_estimates={"paid_model": 0.80},
            evidence=evidence,
        )
        assert signal is None

        signals = await initialized_db.get_recent_signals(n=5)
        assert signals[0]["action"] == "OUTSIDE_ZONE"


# ---------------------------------------------------------------------------
# Executor tests (DRY RUN)
# ---------------------------------------------------------------------------

class TestExecutorDryRun:
    async def test_dry_run_records_position_without_clob_call(
        self, make_market, initialized_db
    ):
        from execution.executor import Executor
        from forecasting.evidence_gatherer import EvidencePackage
        from signals.signal_generator import Signal

        market = make_market(condition_id="exec-test")
        signal = Signal(
            signal_id=1,
            market=market,
            side="YES",
            calibrated_estimate=0.82,
            market_price=0.72,
            divergence=0.10,
            size_usdc=25.0,
            raw_estimates={"paid_model": 0.82},
            evidence=EvidencePackage(
                market_question="Q?", resolution_criteria="", days_to_resolution=30,
                summarized_articles="", base_rate_hint="", news_trigger="t",
            ),
            action="SIGNAL",
        )

        executor = Executor()
        # Ensure no CLOB client is created during dry run
        assert executor._clob_client is None

        result = await executor.execute_trade(signal, dry_run=True)

        assert result.success
        assert result.dry_run
        assert result.order_id.startswith("DRY-")
        assert result.position_id is not None
        # CLOB client was never touched
        assert executor._clob_client is None

    async def test_dry_run_position_recorded_to_db(self, make_market, initialized_db):
        from execution.executor import Executor
        from forecasting.evidence_gatherer import EvidencePackage
        from signals.signal_generator import Signal

        market = make_market(condition_id="db-record-test")
        signal = Signal(
            signal_id=2,
            market=market,
            side="NO",
            calibrated_estimate=0.55,
            market_price=0.70,
            divergence=0.15,
            size_usdc=30.0,
            raw_estimates={"paid_model": 0.55},
            evidence=EvidencePackage(
                market_question="Q?", resolution_criteria="", days_to_resolution=15,
                summarized_articles="", base_rate_hint="", news_trigger="t",
            ),
            action="SIGNAL",
        )

        # Seed risk state
        await initialized_db.update_risk_state({"current_balance": 500, "total_exposure": 0, "open_position_count": 0})

        executor = Executor()
        result = await executor.execute_trade(signal, dry_run=True)

        assert result.success
        positions = await initialized_db.get_open_positions()
        assert len(positions) == 1
        assert positions[0]["side"] == "NO"


# ---------------------------------------------------------------------------
# Convergence scanner tests
# ---------------------------------------------------------------------------

class TestConvergenceScanner:
    def test_detects_near_certain_yes(self, make_market):
        from signals.convergence_scanner import scan_convergence_opportunities
        # Price at 0.97 YES, resolves in 3 days
        market = make_market(
            condition_id="conv-yes",
            market_price_yes=0.97,
            resolution_date="2026-04-14",  # ~3 days from 2026-04-11
        )
        signals = scan_convergence_opportunities([market])
        assert len(signals) == 1
        assert signals[0].side == "YES"
        assert signals[0].entry_price == pytest.approx(0.97)

    def test_detects_near_certain_no(self, make_market):
        from signals.convergence_scanner import scan_convergence_opportunities
        market = make_market(
            condition_id="conv-no",
            market_price_yes=0.03,  # NO side at 0.97
            resolution_date="2026-04-14",
        )
        signals = scan_convergence_opportunities([market])
        assert len(signals) == 1
        assert signals[0].side == "NO"

    def test_ignores_markets_too_far_from_certain(self, make_market):
        from signals.convergence_scanner import scan_convergence_opportunities
        market = make_market(
            condition_id="not-conv",
            market_price_yes=0.85,  # Not near-certain
            resolution_date="2026-04-14",
        )
        signals = scan_convergence_opportunities([market])
        assert len(signals) == 0

    def test_ignores_markets_too_far_from_resolution(self, make_market):
        from signals.convergence_scanner import scan_convergence_opportunities
        market = make_market(
            condition_id="far-res",
            market_price_yes=0.97,
            resolution_date="2026-08-01",  # >7 days away
        )
        signals = scan_convergence_opportunities([market])
        assert len(signals) == 0

    def test_position_size_capped(self, make_market):
        from signals.convergence_scanner import scan_convergence_opportunities
        from config.settings import settings
        market = make_market(market_price_yes=0.97, resolution_date="2026-04-14")
        signals = scan_convergence_opportunities([market])
        if signals:
            assert signals[0].size_usdc <= settings.trading.max_trade_size_usdc

    def test_empty_market_list(self):
        from signals.convergence_scanner import scan_convergence_opportunities
        assert scan_convergence_opportunities([]) == []
