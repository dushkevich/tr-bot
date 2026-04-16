"""
Convergence scanner: finds near-certain markets ($0.95–$0.99) for capital-stabilizer trades.
No LLM calls — pure price + time-based filter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import settings
from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)

CONVERGENCE_MIN_PRICE = 0.95
CONVERGENCE_MAX_PRICE = 0.99
CONVERGENCE_MAX_DAYS = 7
CONVERGENCE_POSITION_PCT = 0.02  # 1–2% of portfolio per opportunity


@dataclass
class ConvergenceSignal:
    market: Market
    side: str             # 'YES' or 'NO'
    entry_price: float
    expected_payout: float  # Always $1.00
    days_to_resolution: float
    size_usdc: float


def scan_convergence_opportunities(markets: list[Market]) -> list[ConvergenceSignal]:
    """
    Scan for near-certain outcomes where price hasn't yet reached $1.00/$0.00.
    Returns convergence signals (no LLM needed — price + time criteria only).
    """
    from forecasting.evidence_gatherer import _compute_days_to_resolution

    cfg = settings.trading
    portfolio = cfg.max_total_exposure_usdc
    size_per_trade = portfolio * CONVERGENCE_POSITION_PCT

    signals: list[ConvergenceSignal] = []

    for market in markets:
        days = _compute_days_to_resolution(market.resolution_date)

        # YES side near-certain
        if CONVERGENCE_MIN_PRICE <= market.market_price_yes <= CONVERGENCE_MAX_PRICE:
            if days <= CONVERGENCE_MAX_DAYS:
                signals.append(ConvergenceSignal(
                    market=market,
                    side="YES",
                    entry_price=market.market_price_yes,
                    expected_payout=1.0,
                    days_to_resolution=days,
                    size_usdc=min(size_per_trade, cfg.max_trade_size_usdc),
                ))

        # NO side near-certain (equivalent: price_no near $1.00 means price_yes near $0.00)
        elif CONVERGENCE_MIN_PRICE <= market.market_price_no <= CONVERGENCE_MAX_PRICE:
            if days <= CONVERGENCE_MAX_DAYS:
                signals.append(ConvergenceSignal(
                    market=market,
                    side="NO",
                    entry_price=market.market_price_no,
                    expected_payout=1.0,
                    days_to_resolution=days,
                    size_usdc=min(size_per_trade, cfg.max_trade_size_usdc),
                ))

    if signals:
        logger.info("Convergence scanner: %d near-certain opportunities found", len(signals))

    return signals
