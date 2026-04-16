"""
APScheduler-based pipeline scheduler.
Main entry point: python -m pipeline.scheduler
"""
from __future__ import annotations

import asyncio
import logging
import logging.config
import os
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from dashboard.db import init_db
from pipeline.main_loop import Pipeline

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("polymarket_bot.log"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_pipeline: Pipeline | None = None
_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def job_run_pipeline() -> None:
    """Main 15-minute pipeline cycle."""
    global _pipeline
    if _pipeline is None:
        return
    try:
        await _pipeline.run_once()
    except Exception as exc:
        logger.error("Scheduled pipeline run failed: %s", exc, exc_info=True)


async def job_refresh_balance() -> None:
    """Refresh USDC balance every 5 minutes."""
    global _pipeline
    if _pipeline is None:
        return
    try:
        await _pipeline.refresh_balance()
    except Exception as exc:
        logger.warning("Balance refresh failed: %s", exc)


async def job_daily_summary() -> None:
    """Send daily summary at 23:55 UTC."""
    global _pipeline
    if _pipeline is None:
        return
    try:
        await _pipeline.send_daily_summary()
    except Exception as exc:
        logger.error("Daily summary failed: %s", exc)


async def job_portfolio_review() -> None:
    """Optional daily portfolio review at 09:00 UTC."""
    global _pipeline
    if _pipeline is None:
        return
    try:
        await _pipeline.send_portfolio_review()
    except Exception as exc:
        logger.warning("Portfolio review failed: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    global _pipeline, _scheduler

    cfg = settings.system

    # Print startup banner
    mode = "DRY RUN (paper trading)" if cfg.dry_run else "LIVE TRADING"
    logger.info("=" * 60)
    logger.info("Polymarket AI Geopolitical Trading Bot")
    logger.info("Mode: %s", mode)
    logger.info("Scan interval: %ds (%d min)", cfg.scan_interval_seconds, cfg.scan_interval_seconds // 60)
    logger.info("DB: %s", cfg.db_path)
    logger.info("=" * 60)

    if cfg.dry_run:
        logger.warning(
            "DRY RUN mode enabled. No real orders will be placed. "
            "All signals will be recorded to the database."
        )

    # Initialize database
    await init_db()
    logger.info("Database initialized.")

    # Initialize Discord bot (optional)
    discord_bot = None
    discord_cfg = settings.discord
    if discord_cfg.bot_token:
        try:
            from discord_bot.bot import DiscordBot
            discord_bot = DiscordBot()
            logger.info("Discord bot configured.")
        except Exception as exc:
            logger.warning("Discord bot failed to initialize: %s", exc)

    # Initialize pipeline
    _pipeline = Pipeline(discord_bot=discord_bot)
    logger.info("Pipeline initialized.")

    # Run the pipeline once immediately on startup
    logger.info("Running initial pipeline cycle...")
    await job_run_pipeline()
    await job_refresh_balance()

    # Set up scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Main pipeline: every N seconds (default: 900 = 15 min)
    _scheduler.add_job(
        job_run_pipeline,
        trigger=IntervalTrigger(seconds=cfg.scan_interval_seconds),
        id="main_pipeline",
        name="Main Pipeline",
        max_instances=1,  # Prevent overlapping runs
        coalesce=True,
    )

    # Balance refresh: every 5 minutes
    _scheduler.add_job(
        job_refresh_balance,
        trigger=IntervalTrigger(seconds=cfg.balance_refresh_seconds),
        id="balance_refresh",
        name="Balance Refresh",
        max_instances=1,
    )

    # Daily summary: 23:55 UTC
    _scheduler.add_job(
        job_daily_summary,
        trigger=CronTrigger(hour=discord_cfg.daily_summary_hour, minute=discord_cfg.daily_summary_minute),
        id="daily_summary",
        name="Daily Summary",
    )

    # Portfolio review: 09:00 UTC (optional, costs one paid model call)
    _scheduler.add_job(
        job_portfolio_review,
        trigger=CronTrigger(hour=discord_cfg.portfolio_review_hour, minute=discord_cfg.portfolio_review_minute),
        id="portfolio_review",
        name="Portfolio Review",
    )

    _scheduler.start()
    logger.info("Scheduler started. Jobs: %s", [j.name for j in _scheduler.get_jobs()])

    # Start Discord bot in background if configured
    if discord_bot:
        try:
            asyncio.create_task(discord_bot.start(discord_cfg.bot_token))
        except Exception as exc:
            logger.warning("Could not start Discord bot: %s", exc)

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
