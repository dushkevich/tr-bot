"""
Calibration bootstrap script.

Fetches historically resolved Polymarket geopolitical markets from Gamma API,
runs the forecasting pipeline on them retroactively, and populates calibration_data.
Then trains an initial Platt Scaling model.

This solves the cold-start problem — run this before going live.

Usage: python scripts/build_calibration.py [--limit 50]
"""
import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main(limit: int = 50, dry_run: bool = True):
    from config.settings import settings
    from dashboard.db import init_db, get_calibration_count, record_calibration_data, get_calibration_data
    from forecasting.calibration import PlattCalibrator
    from forecasting.model_router import ModelRouter
    from forecasting.decomposer import decompose_question
    from forecasting.evidence_gatherer import gather_evidence
    from forecasting.llm_forecaster import estimate_probability
    from ingestion.market_fetcher import MarketFetcher, Market
    from ingestion.gdelt_client import GDELTClient

    print("=" * 60)
    print("Polymarket Bot — Calibration Bootstrap")
    print("=" * 60)
    print(f"Target: {limit} resolved markets")
    print()

    await init_db()

    existing_count = await get_calibration_count()
    if existing_count >= settings.calibration.cold_start_min_samples:
        print(f"Already have {existing_count} calibration samples — skipping bootstrap.")
        print("Run with --force to overwrite.")
        return

    fetcher = MarketFetcher()
    router = ModelRouter()
    gdelt = GDELTClient()

    # Fetch resolved geopolitical markets
    logger.info("Fetching resolved markets from Gamma API...")
    since = datetime.now(timezone.utc) - timedelta(days=180)  # Last 6 months

    resolved_markets = await fetcher.get_resolved_markets(since)
    logger.info("Found %d resolved markets", len(resolved_markets))

    if not resolved_markets:
        print("No resolved markets found. The Gamma API may not be returning historical data.")
        print("You can manually populate calibration_data from your paper trading signals.")
        return

    processed = 0
    for rm in resolved_markets[:limit]:
        try:
            logger.info("Processing: %s (outcome=%s)", rm.question[:60], rm.resolution_outcome)

            # Create a mock Market object for the forecasting pipeline
            market = Market(
                condition_id=rm.condition_id,
                event_id="",
                question=rm.question,
                category="geopolitical",
                market_price_yes=0.5,  # We don't have the historical price — use neutral
                market_price_no=0.5,
                volume=0,
                liquidity=0,
                neg_risk=False,
                fees_enabled=False,
                accepting_orders=False,
                resolution_date=rm.resolved_at,
                resolved=True,
                resolution_outcome=rm.resolution_outcome,
            )

            # Fetch current GDELT articles (best approximation without historical data)
            articles = await gdelt.get_geopolitical_articles()

            # Run forecasting pipeline
            sub_questions = await decompose_question(market, router)
            evidence = await gather_evidence(market, articles, router)
            forecast = await estimate_probability(market, sub_questions, evidence, router)

            actual_outcome = 1 if rm.resolution_outcome == "YES" else 0
            await record_calibration_data({
                "market_condition_id": rm.condition_id,
                "predicted_probability": forecast.raw_probability,
                "actual_outcome": actual_outcome,
                "category": "geopolitical",
            })

            processed += 1
            logger.info(
                "[%d/%d] %s → predicted %.3f, actual %s",
                processed, min(limit, len(resolved_markets)),
                rm.condition_id[:12], forecast.raw_probability, rm.resolution_outcome,
            )

            # Small delay to respect rate limits
            await asyncio.sleep(2)

        except Exception as exc:
            logger.warning("Failed to process %s: %s", rm.condition_id[:12], exc)

    print(f"\nProcessed {processed} resolved markets.")

    # Train the calibrator
    cal_data = await get_calibration_data()
    if len(cal_data) >= settings.calibration.cold_start_min_samples:
        preds = [r["predicted_probability"] for r in cal_data]
        outcomes = [r["actual_outcome"] for r in cal_data]

        calibrator = PlattCalibrator()
        calibrator.fit(preds, outcomes)
        calibrator.save()
        brier = calibrator.brier_score(preds, outcomes)
        print(f"Calibrator trained on {len(cal_data)} samples. Brier score: {brier:.4f}")
        if brier < 0.25:
            print("✓ Brier score beats random baseline (0.25) — good calibration!")
        else:
            print("⚠ Brier score above random baseline. More data needed for reliable calibration.")
    else:
        print(f"Only {len(cal_data)} samples collected — need {settings.calibration.cold_start_min_samples} to train.")
        print("Run the paper trading pipeline for a few weeks to collect more data.")

    print("\nDone! Check dashboard → Calibration Monitor.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap calibration data")
    parser.add_argument("--limit", type=int, default=50, help="Number of resolved markets to process")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit))
