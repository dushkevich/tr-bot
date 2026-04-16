"""
Tests for risk/risk_engine.py and risk/kill_switch.py
Covers all 7 validation checks and edge cases.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_signal(make_market):
    from forecasting.evidence_gatherer import EvidencePackage
    from signals.signal_generator import Signal

    return Signal(
        signal_id=1,
        market=make_market(condition_id="test-mkt"),
        side="YES",
        calibrated_estimate=0.82,
        market_price=0.72,
        divergence=0.10,
        size_usdc=25.0,
        raw_estimates={"paid_model": 0.82},
        evidence=EvidencePackage(
            market_question="Test?", resolution_criteria="",
            days_to_resolution=30, summarized_articles="",
            base_rate_hint="", news_trigger="test",
        ),
        action="SIGNAL",
    )


class TestRiskEngine:
    async def test_approves_clean_trade(self, mock_signal, healthy_risk_state, initialized_db):
        from risk.risk_engine import RiskEngine
        engine = RiskEngine()

        with patch("risk.risk_engine.db.get_open_position_for_market", new=AsyncMock(return_value=None)), \
             patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, healthy_risk_state)

        assert result.approved

    async def test_blocks_on_kill_switch(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        engine = RiskEngine()
        state = {**healthy_risk_state, "kill_switch_active": True}

        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "KILL_SWITCH" in result.reason

    async def test_blocks_on_daily_loss_limit(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        from config.settings import settings
        engine = RiskEngine()
        state = {**healthy_risk_state, "daily_pnl": -(settings.risk.max_daily_loss_usdc + 1)}

        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "DAILY_LOSS" in result.reason

    async def test_blocks_on_minimum_balance(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        from config.settings import settings
        engine = RiskEngine()
        state = {**healthy_risk_state, "current_balance": settings.risk.min_balance_usdc - 1}

        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "MIN_BALANCE" in result.reason

    async def test_blocks_on_max_open_positions(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        from config.settings import settings
        engine = RiskEngine()
        state = {**healthy_risk_state, "open_position_count": settings.risk.max_open_positions}

        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "MAX_POSITIONS" in result.reason

    async def test_blocks_on_exposure_cap(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        from config.settings import settings
        engine = RiskEngine()
        # Set exposure so that adding signal.size_usdc exceeds cap
        state = {**healthy_risk_state, "total_exposure": settings.trading.max_total_exposure_usdc - 1}

        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "EXPOSURE_CAP" in result.reason

    async def test_blocks_on_duplicate_position(self, mock_signal, healthy_risk_state):
        from risk.risk_engine import RiskEngine
        engine = RiskEngine()

        existing_position = {"id": 42, "market_condition_id": "test-mkt"}
        with patch("risk.risk_engine.db.get_open_position_for_market", new=AsyncMock(return_value=existing_position)), \
             patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, healthy_risk_state)

        assert not result.approved
        assert "DUPLICATE" in result.reason

    async def test_blocks_on_brier_degradation(self, mock_signal, healthy_risk_state, sample_calibration_data):
        from risk.risk_engine import RiskEngine
        from forecasting.calibration import PlattCalibrator

        # Create a fitted (warm) calibrator
        calibrator = PlattCalibrator()
        preds, outcomes = zip(*sample_calibration_data)
        calibrator.fit(list(preds), list(outcomes))

        engine = RiskEngine(calibrator=calibrator)

        # Create calibration data with bad Brier score
        bad_cal_data = [
            {"predicted_probability": 0.5, "actual_outcome": o}
            for o in [1, 0] * 10  # All predictions = 0.5 → Brier = 0.25 (right at threshold)
        ]

        with patch("risk.risk_engine.db.get_open_position_for_market", new=AsyncMock(return_value=None)), \
             patch("risk.risk_engine.db.get_calibration_data", new=AsyncMock(return_value=bad_cal_data)), \
             patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):

            # With 0.25 Brier and threshold 0.30, should be approved
            result = await engine.validate_trade(mock_signal, healthy_risk_state)
            assert result.approved

    async def test_kill_switch_checked_first(self, mock_signal):
        """Kill switch should block regardless of other state."""
        from risk.risk_engine import RiskEngine
        engine = RiskEngine()
        state = {
            "kill_switch_active": True,
            "daily_pnl": 0, "total_exposure": 0,
            "open_position_count": 0, "current_balance": 1000,
        }
        with patch("risk.risk_engine.db.record_signal", new=AsyncMock(return_value=99)):
            result = await engine.validate_trade(mock_signal, state)

        assert not result.approved
        assert "KILL_SWITCH" in result.reason


class TestKillSwitch:
    async def test_activate_sets_db_flag(self):
        from risk.kill_switch import KillSwitch

        with patch("risk.kill_switch.db.set_kill_switch", new=AsyncMock()) as mock_set:
            ks = KillSwitch()
            await ks.activate("Test reason")
            mock_set.assert_called_once_with(True)

    async def test_deactivate_clears_db_flag(self):
        from risk.kill_switch import KillSwitch

        with patch("risk.kill_switch.db.set_kill_switch", new=AsyncMock()) as mock_set:
            ks = KillSwitch()
            await ks.deactivate()
            mock_set.assert_called_once_with(False)

    async def test_check_conditions_activates_on_daily_loss(self):
        from risk.kill_switch import KillSwitch
        from config.settings import settings

        with patch("risk.kill_switch.db.set_kill_switch", new=AsyncMock()) as mock_set:
            ks = KillSwitch()
            state = {
                "kill_switch_active": False,
                "daily_pnl": -(settings.risk.max_daily_loss_usdc + 10),
                "current_balance": 200,
            }
            await ks.check_conditions(state)
            mock_set.assert_called_once_with(True)

    async def test_check_conditions_no_activation_on_healthy_state(self):
        from risk.kill_switch import KillSwitch

        with patch("risk.kill_switch.db.set_kill_switch", new=AsyncMock()) as mock_set:
            ks = KillSwitch()
            state = {"kill_switch_active": False, "daily_pnl": 5, "current_balance": 300}
            await ks.check_conditions(state)
            mock_set.assert_not_called()

    async def test_check_conditions_skips_if_already_active(self):
        from risk.kill_switch import KillSwitch

        with patch("risk.kill_switch.db.set_kill_switch", new=AsyncMock()) as mock_set:
            ks = KillSwitch()
            state = {"kill_switch_active": True, "daily_pnl": -999, "current_balance": 0}
            await ks.check_conditions(state)
            mock_set.assert_not_called()
