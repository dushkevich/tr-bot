"""
Risk engine: validates trade signals against all risk rules.
All blocks are logged to the signals table with risk_block_reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import settings
from dashboard import db
from signals.signal_generator import Signal

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    approved: bool
    reason: str  # Empty if approved, block reason if rejected


class RiskEngine:
    """
    7-check validation chain. Any failed check blocks the trade.
    """

    def __init__(self, calibrator=None) -> None:
        self._cfg = settings.risk
        self._calibrator = calibrator  # PlattCalibrator — for Brier score check

    async def validate_trade(
        self, signal: Signal, risk_state: dict
    ) -> ValidationResult:
        """
        Run all risk checks. Returns first failure or approval.
        Updates signal in DB with risk_block_reason on block.
        """
        checks = [
            self._check_kill_switch,
            self._check_daily_loss,
            self._check_min_balance,
            self._check_max_positions,
            self._check_exposure_cap,
            self._check_duplicate_position,
            self._check_brier_score,
        ]

        for check in checks:
            result = await check(signal, risk_state)
            if not result.approved:
                # Update the signal record with the block reason
                await db.record_signal({
                    "market_condition_id": signal.market.condition_id,
                    "market_price": signal.market_price,
                    "model_estimate": signal.calibrated_estimate,
                    "raw_estimates": signal.raw_estimates,
                    "ensemble_raw": signal.raw_estimates.get("ensemble_raw", signal.calibrated_estimate),
                    "divergence": signal.divergence,
                    "news_trigger": signal.evidence.news_trigger,
                    "evidence_summary": signal.evidence.summarized_articles[:500],
                    "reasoning": "",
                    "action": "RISK_BLOCKED",
                    "risk_block_reason": result.reason,
                })
                logger.info(
                    "Trade BLOCKED for %s: %s",
                    signal.market.condition_id[:12], result.reason,
                )
                return result

        logger.info(
            "Trade APPROVED for %s (size=$%.2f)",
            signal.market.condition_id[:12], signal.size_usdc,
        )
        return ValidationResult(approved=True, reason="")

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    async def _check_kill_switch(self, signal: Signal, risk_state: dict) -> ValidationResult:
        if risk_state.get("kill_switch_active"):
            return ValidationResult(False, "KILL_SWITCH_ACTIVE")
        return ValidationResult(True, "")

    async def _check_daily_loss(self, signal: Signal, risk_state: dict) -> ValidationResult:
        daily_pnl = risk_state.get("daily_pnl", 0)
        if daily_pnl <= -self._cfg.max_daily_loss_usdc:
            return ValidationResult(
                False,
                f"DAILY_LOSS_LIMIT: daily P&L {daily_pnl:.2f} <= -{self._cfg.max_daily_loss_usdc}",
            )
        return ValidationResult(True, "")

    async def _check_min_balance(self, signal: Signal, risk_state: dict) -> ValidationResult:
        balance = risk_state.get("current_balance", 0)
        if balance <= self._cfg.min_balance_usdc:
            return ValidationResult(
                False,
                f"MIN_BALANCE: balance {balance:.2f} <= {self._cfg.min_balance_usdc}",
            )
        return ValidationResult(True, "")

    async def _check_max_positions(self, signal: Signal, risk_state: dict) -> ValidationResult:
        count = risk_state.get("open_position_count", 0)
        if count >= self._cfg.max_open_positions:
            return ValidationResult(
                False,
                f"MAX_POSITIONS: {count} >= {self._cfg.max_open_positions}",
            )
        return ValidationResult(True, "")

    async def _check_exposure_cap(self, signal: Signal, risk_state: dict) -> ValidationResult:
        exposure = risk_state.get("total_exposure", 0)
        max_exposure = settings.trading.max_total_exposure_usdc
        if exposure + signal.size_usdc > max_exposure:
            return ValidationResult(
                False,
                f"EXPOSURE_CAP: {exposure:.2f} + {signal.size_usdc:.2f} > {max_exposure}",
            )
        return ValidationResult(True, "")

    async def _check_duplicate_position(self, signal: Signal, risk_state: dict) -> ValidationResult:
        existing = await db.get_open_position_for_market(signal.market.condition_id)
        if existing:
            return ValidationResult(
                False,
                f"DUPLICATE_POSITION: already have open position #{existing['id']} in this market",
            )
        return ValidationResult(True, "")

    async def _check_brier_score(self, signal: Signal, risk_state: dict) -> ValidationResult:
        if self._calibrator is None:
            return ValidationResult(True, "")

        # Only check if calibrator is warm (has data)
        if not self._calibrator.is_warm():
            return ValidationResult(True, "")

        # Get recent calibration data for Brier score
        cal_data = await db.get_calibration_data()
        if len(cal_data) < 10:
            return ValidationResult(True, "")

        recent = cal_data[-50:]  # Last 50 resolved markets
        preds = [r["predicted_probability"] for r in recent]
        outcomes = [r["actual_outcome"] for r in recent]
        brier = self._calibrator.brier_score(preds, outcomes)

        if brier > self._cfg.brier_score_pause_threshold:
            return ValidationResult(
                False,
                f"BRIER_DEGRADED: score {brier:.3f} > threshold {self._cfg.brier_score_pause_threshold}",
            )
        return ValidationResult(True, "")
