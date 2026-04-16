"""
Order executor: places FOK orders via CLOB API with retry/backoff.
In DRY_RUN mode: simulates fills, records to DB, skips CLOB call.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from config.settings import settings
from dashboard import db
from signals.signal_generator import Signal

logger = logging.getLogger(__name__)

# CLOB rate limit: 60 orders per minute
MAX_ORDERS_PER_MINUTE = 60
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2.0  # seconds, doubled each retry


@dataclass
class ExecutionResult:
    success: bool
    order_id: str | None
    filled_price: float
    filled_size: float
    position_id: int | None
    dry_run: bool
    error: str | None = None


class Executor:
    """
    Handles order placement via Polymarket CLOB API.
    FOK (Fill-or-Kill): fills immediately at target price or cancels.
    """

    def __init__(self, discord_bot=None) -> None:
        self._cfg = settings.system
        self._discord = discord_bot
        self._clob_client = None
        self._order_timestamps: deque[float] = deque()

    def _get_clob(self):
        if self._clob_client is None:
            try:
                from py_clob_client.client import ClobClient
                from py_clob_client.clob_types import ApiCreds

                self._clob_client = ClobClient(
                    "https://clob.polymarket.com",
                    key=self._cfg.poly_private_key,
                    chain_id=137,
                )
                # Create/derive API credentials
                creds = self._clob_client.create_or_derive_api_creds()
                self._clob_client.set_api_creds(creds)
            except Exception as exc:
                logger.error("Failed to initialize CLOB client: %s", exc)
        return self._clob_client

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _wait_for_order_slot(self) -> None:
        """Ensure we don't exceed 60 orders/minute."""
        now = time.time()
        cutoff = now - 60
        while self._order_timestamps and self._order_timestamps[0] < cutoff:
            self._order_timestamps.popleft()

        if len(self._order_timestamps) >= MAX_ORDERS_PER_MINUTE:
            oldest = self._order_timestamps[0]
            wait = 60 - (now - oldest) + 0.1
            logger.debug("Order rate limit: waiting %.1fs", wait)
            await asyncio.sleep(wait)

        self._order_timestamps.append(time.time())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_trade(self, signal: Signal, dry_run: bool | None = None) -> ExecutionResult:
        """
        Execute a trade signal. Handles both dry run and live modes.
        Retries up to MAX_RETRIES on transient failures.
        """
        if dry_run is None:
            dry_run = self._cfg.dry_run

        market = signal.market
        side = signal.side
        size_usdc = signal.size_usdc
        target_price = market.market_price_yes if side == "YES" else market.market_price_no

        if dry_run:
            return await self._execute_dry_run(signal, target_price)

        # Live execution with retry
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                await self._wait_for_order_slot()
                result = await self._place_fok_order_live(signal, target_price)
                if result.success:
                    return result
                last_error = result.error
            except Exception as exc:
                last_error = str(exc)
                wait = BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Order attempt %d/%d failed for %s: %s — retrying in %.1fs",
                    attempt + 1, MAX_RETRIES, market.condition_id[:12], exc, wait,
                )
                await asyncio.sleep(wait)

        # All retries exhausted
        logger.error(
            "Order FAILED after %d attempts for %s: %s",
            MAX_RETRIES, market.condition_id[:12], last_error,
        )
        if self._discord:
            try:
                await self._discord.send_alert(
                    title="CLOB Order Failed",
                    description=f"Market: {market.question[:100]}\nError: {last_error}",
                    color="red",
                )
            except Exception:
                pass
        return ExecutionResult(
            success=False, order_id=None, filled_price=0, filled_size=0,
            position_id=None, dry_run=False, error=last_error,
        )

    async def _execute_dry_run(self, signal: Signal, target_price: float) -> ExecutionResult:
        """Simulate fill at current ask price. Records position to DB."""
        # In dry run, "fill" at the target price
        filled_price = target_price
        filled_size = signal.size_usdc / filled_price if filled_price > 0 else 0
        entry_cost = signal.size_usdc
        order_id = f"DRY-{signal.signal_id}-{int(time.time())}"

        position_id = await db.record_position({
            "market_condition_id": signal.market.condition_id,
            "signal_id": signal.signal_id,
            "side": signal.side,
            "entry_price": filled_price,
            "entry_size": filled_size,
            "entry_cost_usdc": entry_cost,
            "model_estimate_at_entry": signal.calibrated_estimate,
            "current_market_price": signal.market_price,
            "order_id": order_id,
        })

        # Update risk state
        risk_state = await db.get_risk_state()
        await db.update_risk_state({
            "total_exposure": risk_state.get("total_exposure", 0) + entry_cost,
            "open_position_count": risk_state.get("open_position_count", 0) + 1,
        })

        logger.info(
            "[DRY RUN] Simulated %s fill: %s @ %.4f, size=%.2f shares, cost=$%.2f",
            signal.side, signal.market.condition_id[:12],
            filled_price, filled_size, entry_cost,
        )

        return ExecutionResult(
            success=True,
            order_id=order_id,
            filled_price=filled_price,
            filled_size=filled_size,
            position_id=position_id,
            dry_run=True,
        )

    async def _place_fok_order_live(self, signal: Signal, target_price: float) -> ExecutionResult:
        """Place actual FOK order via CLOB API."""
        client = self._get_clob()
        if client is None:
            raise RuntimeError("CLOB client not initialized")

        from py_clob_client.clob_types import OrderArgs, OrderType

        token_id = (
            signal.market.token_id_yes
            if signal.side == "YES"
            else signal.market.token_id_no
        )

        if not token_id:
            raise ValueError(f"No token_id for {signal.side} side of market {signal.market.condition_id}")

        # Number of shares = USDC / price
        size_shares = signal.size_usdc / target_price if target_price > 0 else 0
        size_shares = round(size_shares, 6)

        order_args = OrderArgs(
            token_id=token_id,
            price=target_price,
            size=size_shares,
            side="BUY",
        )

        # FOK = Fill or Kill
        order = await asyncio.to_thread(
            client.create_and_post_order, order_args, OrderType.FOK
        )

        if not order:
            return ExecutionResult(
                success=False, order_id=None, filled_price=0, filled_size=0,
                position_id=None, dry_run=False, error="Order rejected (FOK not filled)",
            )

        order_id = order.get("orderID", order.get("id", ""))
        status = order.get("status", "")

        if status not in ("matched", "MATCHED", "filled", "FILLED"):
            return ExecutionResult(
                success=False, order_id=order_id, filled_price=0, filled_size=0,
                position_id=None, dry_run=False,
                error=f"Order status: {status} (expected filled)",
            )

        # Record position
        filled_price = float(order.get("price", target_price))
        filled_size = float(order.get("size", size_shares))
        entry_cost = filled_price * filled_size

        position_id = await db.record_position({
            "market_condition_id": signal.market.condition_id,
            "signal_id": signal.signal_id,
            "side": signal.side,
            "entry_price": filled_price,
            "entry_size": filled_size,
            "entry_cost_usdc": entry_cost,
            "model_estimate_at_entry": signal.calibrated_estimate,
            "current_market_price": signal.market_price,
            "order_id": order_id,
        })

        # Update risk state
        risk_state = await db.get_risk_state()
        await db.update_risk_state({
            "total_exposure": risk_state.get("total_exposure", 0) + entry_cost,
            "open_position_count": risk_state.get("open_position_count", 0) + 1,
        })

        logger.info(
            "LIVE order filled: %s %s @ %.4f, size=%.2f, cost=$%.2f, order_id=%s",
            signal.side, signal.market.condition_id[:12],
            filled_price, filled_size, entry_cost, order_id,
        )

        return ExecutionResult(
            success=True,
            order_id=order_id,
            filled_price=filled_price,
            filled_size=filled_size,
            position_id=position_id,
            dry_run=False,
        )

    async def cancel_order(self, order_id: str) -> None:
        client = self._get_clob()
        if client is None:
            return
        try:
            await asyncio.to_thread(client.cancel, order_id)
            logger.info("Order %s cancelled", order_id)
        except Exception as exc:
            logger.warning("Failed to cancel order %s: %s", order_id, exc)
