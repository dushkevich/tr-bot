"""
Backtest: replay stored signals against resolved markets.
Computes hypothetical P&L, Brier score, win rate.

Usage: python scripts/backtest.py [--days 30]
"""
import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main(days: int = 30):
    from dashboard.db import init_db, get_calibration_data, get_recent_signals
    from forecasting.calibration import PlattCalibrator

    await init_db()
    print("=" * 60)
    print(f"Backtest — Last {days} days of signals")
    print("=" * 60)

    # Get all calibration data (resolved markets with predictions)
    cal_data = await get_calibration_data()
    if not cal_data:
        print("No calibration data found. Run build_calibration.py first, or wait for markets to resolve.")
        return

    resolved_map = {r["market_condition_id"]: r for r in cal_data}

    # Get signals that were TRADED
    signals = await get_recent_signals(n=10000)
    traded_signals = [s for s in signals if s["action"] == "TRADED"]

    print(f"Total resolved markets: {len(cal_data)}")
    print(f"Total traded signals: {len(traded_signals)}")
    print()

    # Hypothetical P&L from all signals above threshold (not just traded)
    threshold_signals = [
        s for s in signals
        if s["divergence"] and s["divergence"] >= 0.08
        and s["market_condition_id"] in resolved_map
    ]

    print(f"Signals above threshold with known outcomes: {len(threshold_signals)}")

    if not threshold_signals:
        print("No signals above threshold with resolved outcomes yet.")
        return

    # Compute hypothetical P&L
    total_pnl = 0
    wins = 0
    losses = 0
    position_size = 50  # Assume $50 per trade

    for sig in threshold_signals:
        resolution = resolved_map[sig["market_condition_id"]]
        actual = resolution["actual_outcome"]  # 1=YES, 0=NO

        # Would we have bought YES or NO?
        est = sig["model_estimate"]
        price = sig["market_price"]
        side_yes = est > price  # True = BUY YES

        # Did we win?
        won = (side_yes and actual == 1) or (not side_yes and actual == 0)

        if won:
            # Won: profit = (1 - entry_price) / entry_price * size
            entry_price = price if side_yes else (1 - price)
            pnl = (1 - entry_price) * (position_size / entry_price)
            wins += 1
        else:
            pnl = -position_size
            losses += 1

        total_pnl += pnl

    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades else 0

    print(f"\nHypothetical Results (${position_size}/trade, {total_trades} trades):")
    print(f"  Win Rate:     {win_rate:.1f}%  ({wins}W/{losses}L)")
    print(f"  Total P&L:    ${total_pnl:.2f}")
    print(f"  Avg P&L/trade: ${total_pnl/total_trades:.2f}" if total_trades else "")

    # Calibration analysis
    print()
    calibrator = PlattCalibrator()
    preds = [r["predicted_probability"] for r in cal_data]
    outcomes = [r["actual_outcome"] for r in cal_data]
    brier = calibrator.brier_score(preds, outcomes)
    print(f"Calibration (Brier Score): {brier:.4f}")
    print(f"  Random baseline:  0.2500")
    print(f"  Your model:       {brier:.4f}  {'✓ BEATS baseline' if brier < 0.25 else '✗ WORSE than random'}")

    # Edge analysis
    print()
    print("Edge Analysis by Divergence Bucket:")
    buckets = [(0.08, 0.12), (0.12, 0.16), (0.16, 0.20), (0.20, 1.0)]
    for lo, hi in buckets:
        bucket_sigs = [
            s for s in threshold_signals
            if lo <= s["divergence"] < hi
        ]
        if not bucket_sigs:
            continue
        bucket_wins = sum(
            1 for s in bucket_sigs
            if (s["model_estimate"] > s["market_price"]) == (resolved_map[s["market_condition_id"]]["actual_outcome"] == 1)
        )
        print(f"  {lo*100:.0f}-{hi*100:.0f}%: {len(bucket_sigs)} trades, {bucket_wins/len(bucket_sigs)*100:.0f}% win rate")

    print()
    print("Backtest complete. Note: past performance doesn't guarantee future results.")
    print("Real execution has slippage, FOK rejection rates, and timing differences.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest stored signals")
    parser.add_argument("--days", type=int, default=30, help="Days of history to analyze")
    args = parser.parse_args()
    asyncio.run(main(days=args.days))
