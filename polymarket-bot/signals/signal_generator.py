"""
Signal generator: compares calibrated estimate vs. market price,
computes fractional Kelly position size, records signal to DB.
Always records — even when no trade is taken.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import settings
from dashboard import db
from forecasting.evidence_gatherer import EvidencePackage
from ingestion.market_fetcher import Market

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    signal_id: int                  # DB row ID
    market: Market
    side: str                       # 'YES' or 'NO'
    calibrated_estimate: float
    market_price: float
    divergence: float
    size_usdc: float                # Recommended position size
    raw_estimates: dict             # {'model': probability}
    evidence: EvidencePackage
    action: str                     # 'SIGNAL' (pending risk check)


async def generate_signal(
    market: Market,
    calibrated_estimate: float,
    raw_estimates: dict,
    evidence: EvidencePackage,
    reasoning: str = "",
) -> Signal | None:
    """
    Generate a trade signal if divergence threshold is met AND market is in trading zone.
    ALWAYS records the signal to DB regardless of whether it exceeds the threshold.
    Returns Signal if tradeable, None if below threshold or outside trading zone.
    """
    cfg_trading = settings.trading
    cfg_market = settings.market

    market_price = market.market_price_yes
    divergence = abs(calibrated_estimate - market_price)

    # Determine direction
    if calibrated_estimate > market_price:
        side = "YES"
        edge = calibrated_estimate - market_price
        # Kelly formula for binary bet: f = (p*(1/cost - 1) - (1-p)) / (1/cost - 1)
        # Simplified: f = edge / (1 - market_price)  (odds = 1/market_price - 1 ≈ (1-p)/p)
        odds = (1.0 - market_price) / market_price if market_price > 0 else 1.0
        kelly_full = (edge * (1 + odds) - (1 - calibrated_estimate)) / odds if odds > 0 else 0
    else:
        side = "NO"
        edge = market_price - calibrated_estimate
        odds = market_price / (1.0 - market_price) if (1.0 - market_price) > 0 else 1.0
        kelly_full = (edge * (1 + odds) - (1 - (1 - calibrated_estimate))) / odds if odds > 0 else 0

    kelly_full = max(0.0, kelly_full)
    fractional_kelly = kelly_full * cfg_trading.kelly_fraction

    # Position size: fractional Kelly × portfolio (use exposure cap as proxy for portfolio)
    portfolio_estimate = cfg_trading.max_total_exposure_usdc
    raw_size = fractional_kelly * portfolio_estimate

    # Apply caps
    market_cap = portfolio_estimate * cfg_trading.max_single_market_pct
    size_usdc = min(raw_size, cfg_trading.max_trade_size_usdc, market_cap)
    size_usdc = max(1.0, size_usdc)  # At least $1

    # Determine action for DB record
    in_trading_zone = cfg_market.trading_min <= market_price <= cfg_market.trading_max
    above_threshold = divergence >= cfg_trading.divergence_threshold

    if above_threshold and in_trading_zone:
        action = "SIGNAL"
    elif not above_threshold:
        action = "BELOW_THRESHOLD"
    else:
        action = "OUTSIDE_ZONE"

    # Always record to DB
    signal_id = await db.record_signal({
        "market_condition_id": market.condition_id,
        "market_price": market_price,
        "model_estimate": calibrated_estimate,
        "raw_estimates": raw_estimates,
        "ensemble_raw": raw_estimates.get("ensemble_raw", calibrated_estimate),
        "divergence": divergence,
        "news_trigger": evidence.news_trigger,
        "evidence_summary": evidence.summarized_articles[:500],
        "reasoning": reasoning[:2000] if reasoning else "",
        "action": action,
        "risk_block_reason": None,
    })

    if action != "SIGNAL":
        logger.info(
            "Signal %s for %s (div=%.3f, price=%.2f) — %s",
            action, market.condition_id[:12], divergence, market_price, action,
        )
        return None

    logger.info(
        "Signal GENERATED: %s %s @ %.2f (model=%.2f, div=%.3f, size=$%.2f)",
        side, market.condition_id[:12], market_price, calibrated_estimate, divergence, size_usdc,
    )

    return Signal(
        signal_id=signal_id,
        market=market,
        side=side,
        calibrated_estimate=calibrated_estimate,
        market_price=market_price,
        divergence=divergence,
        size_usdc=size_usdc,
        raw_estimates=raw_estimates,
        evidence=evidence,
        action="SIGNAL",
    )
