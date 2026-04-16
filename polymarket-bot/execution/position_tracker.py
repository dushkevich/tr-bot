"""
Position tracker: monitors open positions, detects resolutions, flags early-exit candidates.
On resolution: records to calibration_data and updates daily_pnl.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from dashboard import db
from ingestion.market_fetcher import MarketFetcher

logger = logging.getLogger(__name__)

# A position is flagged for early exit when the market moves
# this fraction of the original divergence toward the model estimate
EARLY_EXIT_THRESHOLD_FRACTION = 0.5


@dataclass
class Resolution:
    position_id: int
    market_condition_id: str
    question: str
    outcome: str         # 'YES' or 'NO'
    realized_pnl: float


class PositionTracker:

    def __init__(self, market_fetcher: MarketFetcher) -> None:
        self._fetcher = market_fetcher

    async def update_positions(self) -> None:
        """
        Refresh current market prices for all open positions.
        Flags positions for early exit where appropriate.
        """
        positions = await db.get_open_positions()
        if not positions:
            return

        for pos in positions:
            try:
                price_yes, price_no = await self._fetcher.get_market_price(
                    pos["market_condition_id"]
                )
                current_price = price_yes if pos["side"] == "YES" else price_no

                updates: dict = {"current_market_price": current_price}

                # Check early-exit flag
                entry_price = pos["entry_price"]
                model_est = pos.get("model_estimate_at_entry", entry_price)
                original_divergence = abs(model_est - entry_price)

                if original_divergence > 0:
                    # How far has the market moved toward the model estimate?
                    if pos["side"] == "YES":
                        movement = current_price - entry_price
                        expected_direction = model_est > entry_price
                    else:
                        movement = entry_price - current_price
                        expected_direction = model_est < entry_price

                    if expected_direction and movement >= original_divergence * EARLY_EXIT_THRESHOLD_FRACTION:
                        if not pos.get("early_exit_flagged"):
                            updates["early_exit_flagged"] = True
                            logger.info(
                                "Position #%d flagged for early exit: market moved %.1f%% toward model estimate",
                                pos["id"], (movement / original_divergence) * 100,
                            )

                await db.update_position(pos["id"], updates)

            except Exception as exc:
                logger.warning("Position update failed for #%d: %s", pos["id"], exc)

        # Recalculate total unrealized P&L for risk state
        positions = await db.get_open_positions()
        total_unrealized = sum(
            (p["current_market_price"] - p["entry_price"]) * p["entry_size"]
            for p in positions
        )
        total_exposure = sum(p["entry_cost_usdc"] for p in positions)
        await db.update_risk_state({
            "total_exposure": total_exposure,
            "open_position_count": len(positions),
        })

    async def check_resolved_markets(self) -> list[Resolution]:
        """
        Check if any open positions' markets have been resolved.
        Closes resolved positions, records to calibration_data, updates daily_pnl.
        """
        positions = await db.get_open_positions()
        if not positions:
            return []

        # Fetch recently resolved markets from Gamma API
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=7)
        resolved_markets = await self._fetcher.get_resolved_markets(since)
        resolved_map = {r.condition_id: r for r in resolved_markets}

        resolutions = []
        for pos in positions:
            cid = pos["market_condition_id"]
            if cid not in resolved_map:
                continue

            resolution = resolved_map[cid]
            outcome = resolution.resolution_outcome  # 'YES' or 'NO'

            # Compute realized P&L
            side = pos["side"]
            entry_price = pos["entry_price"]
            entry_size = pos["entry_size"]
            entry_cost = pos["entry_cost_usdc"]

            if outcome == side:
                # Position won — payout is $1.00 per share
                realized_pnl = (1.0 - entry_price) * entry_size
            else:
                # Position lost — lost the entry cost
                realized_pnl = -entry_cost

            now_str = datetime.now(timezone.utc).isoformat()
            exit_price = 1.0 if outcome == side else 0.0

            await db.close_position(
                position_id=pos["id"],
                exit_price=exit_price,
                exit_timestamp=now_str,
                realized_pnl=realized_pnl,
                reason="resolved",
            )

            # Record to calibration_data
            # actual_outcome: 1 if YES resolved, 0 if NO resolved
            actual_outcome = 1 if outcome == "YES" else 0
            await db.record_calibration_data({
                "market_condition_id": cid,
                "predicted_probability": pos.get("model_estimate_at_entry", 0.5),
                "actual_outcome": actual_outcome,
                "category": "geopolitical",
            })

            # Update daily P&L snapshot
            today = datetime.now(timezone.utc).date().isoformat()
            await self._update_daily_pnl(today, realized_pnl)

            # Update risk state daily_pnl
            risk_state = await db.get_risk_state()
            await db.update_risk_state({
                "daily_pnl": risk_state.get("daily_pnl", 0) + realized_pnl,
            })

            resolutions.append(Resolution(
                position_id=pos["id"],
                market_condition_id=cid,
                question=pos.get("question", ""),
                outcome=outcome,
                realized_pnl=realized_pnl,
            ))

            logger.info(
                "Position #%d resolved %s — P&L: $%.2f",
                pos["id"], outcome, realized_pnl,
            )

        return resolutions

    async def compute_unrealized_pnl(self, position: dict, current_price: float) -> float:
        side = position["side"]
        entry_price = position["entry_price"]
        entry_size = position["entry_size"]
        price_diff = (current_price - entry_price) if side == "YES" else (entry_price - current_price)
        return price_diff * entry_size

    async def close_position(
        self, position_id: int, exit_price: float, reason: str
    ) -> None:
        """Manual position close (e.g. early exit)."""
        pos = await db.get_position_by_id(position_id)
        if not pos:
            logger.warning("Position #%d not found", position_id)
            return

        entry_price = pos["entry_price"]
        entry_size = pos["entry_size"]
        entry_cost = pos["entry_cost_usdc"]
        side = pos["side"]

        price_diff = (exit_price - entry_price) if side == "YES" else (entry_price - exit_price)
        realized_pnl = price_diff * entry_size

        now_str = datetime.now(timezone.utc).isoformat()
        await db.close_position(
            position_id=position_id,
            exit_price=exit_price,
            exit_timestamp=now_str,
            realized_pnl=realized_pnl,
            reason=reason,
        )

        # Update daily P&L
        today = datetime.now(timezone.utc).date().isoformat()
        await self._update_daily_pnl(today, realized_pnl)

        risk_state = await db.get_risk_state()
        await db.update_risk_state({
            "daily_pnl": risk_state.get("daily_pnl", 0) + realized_pnl,
        })

        logger.info(
            "Position #%d manually closed @ %.4f, P&L: $%.2f (reason: %s)",
            position_id, exit_price, realized_pnl, reason,
        )

    async def check_early_exit_candidates(self) -> list[dict]:
        """Return all open positions flagged for early exit."""
        positions = await db.get_open_positions()
        return [p for p in positions if p.get("early_exit_flagged")]

    async def _update_daily_pnl(self, date: str, realized_delta: float) -> None:
        """Upsert daily_pnl row with the new realized P&L delta."""
        risk_state = await db.get_risk_state()
        balance = risk_state.get("current_balance", 0)
        await db.upsert_daily_pnl({
            "date": date,
            "starting_balance": balance,
            "ending_balance": balance + realized_delta,
            "realized_pnl": realized_delta,
            "unrealized_pnl": 0,
            "trades_opened": 0,
            "trades_closed": 1,
            "brier_score": None,
        })
