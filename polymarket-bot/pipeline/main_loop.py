"""
Main 15-minute pipeline loop.
Orchestrates: GDELT → market fetch → match → forecast → signal → risk → execute.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from config.settings import settings
from dashboard import db
from execution.executor import Executor
from execution.position_tracker import PositionTracker
from execution.wallet import WalletManager
from forecasting.calibration import PlattCalibrator
from forecasting.decomposer import decompose_question
from forecasting.ensemble import ensemble_estimates
from forecasting.evidence_gatherer import gather_evidence
from forecasting.llm_forecaster import estimate_probability
from forecasting.model_router import ModelRouter
from ingestion.gdelt_client import GDELTClient
from ingestion.market_fetcher import MarketFetcher
from ingestion.matcher import MarketMatcher
from risk.kill_switch import KillSwitch
from risk.risk_engine import RiskEngine
from signals.convergence_scanner import scan_convergence_opportunities
from signals.signal_generator import generate_signal

logger = logging.getLogger(__name__)


class Pipeline:
    """
    Full pipeline orchestrator. Call run_once() to execute one 15-minute cycle.
    """

    def __init__(self, discord_bot=None) -> None:
        self._discord = discord_bot
        self._cfg = settings.system

        # Initialize components
        self._router = ModelRouter()
        self._gdelt = GDELTClient()
        self._fetcher = MarketFetcher()
        self._matcher = MarketMatcher(self._router)
        self._calibrator = PlattCalibrator()
        self._risk_engine = RiskEngine(calibrator=self._calibrator)
        self._executor = Executor(discord_bot=discord_bot)
        self._position_tracker = PositionTracker(self._fetcher)
        self._wallet = WalletManager()
        self._kill_switch = KillSwitch(discord_bot=discord_bot)

        # Load calibrator from disk if available
        self._calibrator.load()

    async def run_once(self) -> dict:
        """
        Execute one full pipeline cycle. Returns a summary dict for logging/monitoring.
        """
        start = datetime.now(timezone.utc)
        summary = {
            "started_at": start.isoformat(),
            "articles_fetched": 0,
            "markets_fetched": 0,
            "markets_matched": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "trades_blocked": 0,
            "resolutions": 0,
            "convergence_opportunities": 0,
            "errors": [],
        }

        try:
            # ----------------------------------------------------------
            # Step 1: Check kill switch
            # ----------------------------------------------------------
            if await self._kill_switch.is_active():
                logger.warning("Kill switch active — skipping pipeline cycle")
                return summary

            # ----------------------------------------------------------
            # Step 2: Fetch GDELT articles
            # ----------------------------------------------------------
            articles = await self._gdelt.get_geopolitical_articles()
            summary["articles_fetched"] = len(articles)

            # ----------------------------------------------------------
            # Step 3: Fetch + pre-filter markets
            # ----------------------------------------------------------
            markets = await self._fetcher.get_active_geo_markets()
            summary["markets_fetched"] = len(markets)

            if not markets:
                logger.info("No markets returned — ending cycle early")
                return summary

            # ----------------------------------------------------------
            # Step 4: Semantic matching (ONE batched free-model request)
            # ----------------------------------------------------------
            matched_pairs = await self._matcher.match(articles, markets)
            summary["markets_matched"] = len(matched_pairs)

            # ----------------------------------------------------------
            # Step 5–11: For each matched market, forecast and trade
            # ----------------------------------------------------------
            risk_state = await db.get_risk_state()

            for market, relevant_articles in matched_pairs:
                try:
                    await self._process_market(market, relevant_articles, risk_state, summary)
                    # Refresh risk state after each potential trade
                    risk_state = await db.get_risk_state()
                except Exception as exc:
                    logger.error("Error processing market %s: %s", market.condition_id[:12], exc)
                    summary["errors"].append(str(exc))

            # ----------------------------------------------------------
            # Step 12: Update position prices + early-exit flagging
            # ----------------------------------------------------------
            await self._position_tracker.update_positions()

            # ----------------------------------------------------------
            # Step 13: Check for resolved markets
            # ----------------------------------------------------------
            resolutions = await self._position_tracker.check_resolved_markets()
            summary["resolutions"] = len(resolutions)

            # Retrain calibrator if new resolutions and retraining needed
            if resolutions and self._calibrator.needs_retraining():
                await self._retrain_calibrator()

            # Notify Discord about resolutions
            if self._discord and resolutions:
                for r in resolutions:
                    try:
                        await self._discord.send_resolution(r)
                    except Exception:
                        pass

            # ----------------------------------------------------------
            # Step 14: Scan for convergence opportunities
            # ----------------------------------------------------------
            convergence = scan_convergence_opportunities(markets)
            summary["convergence_opportunities"] = len(convergence)
            # Convergence trading is logged but NOT auto-executed in Phase 1
            if convergence:
                logger.info("%d convergence opportunities found (not auto-traded in Phase 1)", len(convergence))

            # ----------------------------------------------------------
            # Step 15: Auto-activate kill switch if conditions met
            # ----------------------------------------------------------
            risk_state = await db.get_risk_state()
            await self._kill_switch.check_conditions(risk_state)

        except Exception as exc:
            logger.error("Pipeline cycle failed: %s", exc, exc_info=True)
            summary["errors"].append(str(exc))

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        summary["elapsed_seconds"] = elapsed
        logger.info("Pipeline cycle complete in %.1fs: %s", elapsed, summary)
        return summary

    async def _process_market(
        self, market, relevant_articles, risk_state, summary
    ) -> None:
        """Process a single matched market through the full forecast → trade pipeline."""

        # Step 5: Decompose question [FREE model]
        sub_questions = await decompose_question(market, self._router)

        # Step 6: Gather evidence [FREE model]
        evidence = await gather_evidence(market, relevant_articles, self._router)

        # Step 7: Estimate probability [PAID model]
        forecast = await estimate_probability(market, sub_questions, evidence, self._router)

        # Step 8: Ensemble (single model in Phase 1 — pass through)
        raw_prob = ensemble_estimates([forecast.raw_probability])

        # Step 9: Calibrate
        calibrated = self._calibrator.calibrate(raw_prob)

        raw_estimates = {
            "paid_model": forecast.raw_probability,
            "ensemble_raw": raw_prob,
        }

        # Step 10: Generate signal (always records to DB)
        signal = await generate_signal(
            market=market,
            calibrated_estimate=calibrated,
            raw_estimates=raw_estimates,
            evidence=evidence,
            reasoning=forecast.reasoning,
        )

        if signal is None:
            return

        summary["signals_generated"] += 1

        # Step 11: Risk check
        validation = await self._risk_engine.validate_trade(signal, risk_state)

        if not validation.approved:
            summary["trades_blocked"] += 1
            if self._discord:
                try:
                    await self._discord.send_blocked_signal(signal, validation.reason)
                except Exception:
                    pass
            return

        # Step 12: Execute
        result = await self._executor.execute_trade(signal, dry_run=self._cfg.dry_run)

        if result.success:
            summary["trades_executed"] += 1
            if self._discord:
                try:
                    await self._discord.send_trade_executed(signal, result)
                except Exception:
                    pass
        else:
            summary["errors"].append(f"Execution failed: {result.error}")

    async def _retrain_calibrator(self) -> None:
        """Retrain Platt calibrator from all available calibration data."""
        cal_data = await db.get_calibration_data()
        if len(cal_data) < 20:
            return

        preds = [r["predicted_probability"] for r in cal_data]
        outcomes = [r["actual_outcome"] for r in cal_data]

        self._calibrator.fit(preds, outcomes)
        self._calibrator.save()
        logger.info("Calibrator retrained on %d samples", len(cal_data))

    async def refresh_balance(self) -> None:
        """Refresh current USDC balance in risk_state. Called every 5 minutes."""
        balance = await self._wallet.get_usdc_balance()
        await db.update_risk_state({"current_balance": balance})
        logger.debug("Balance refreshed: $%.2f USDC", balance)

    async def send_daily_summary(self) -> None:
        """Trigger end-of-day summary. Called at 23:55 UTC."""
        if not self._discord:
            return

        # Reset daily P&L counter in risk_state for next day
        risk_state = await db.get_risk_state()
        stats = await db.get_portfolio_stats()
        pnl_data = await db.get_daily_pnl(days=1)

        await self._discord.send_daily_summary(
            risk_state=risk_state,
            portfolio_stats=stats,
            today_pnl=pnl_data[0] if pnl_data else {},
            calibrator=self._calibrator,
        )

        # Reset daily P&L counter
        await db.update_risk_state({"daily_pnl": 0})

    async def send_portfolio_review(self) -> None:
        """
        Optional daily portfolio review via PAID model (09:00 UTC).
        Summarizes open positions + today's news → brief risk narrative.
        """
        try:
            positions = await db.get_open_positions()
            articles = await self._gdelt.get_geopolitical_articles()

            if not positions:
                return

            position_summary = "\n".join(
                f"- {p.get('question', p['market_condition_id'][:20])}: "
                f"side={p['side']}, entry={p['entry_price']:.2f}, "
                f"current={p['current_market_price']:.2f}"
                for p in positions
            )
            news_summary = "\n".join(art.title for art in articles[:10])

            prompt = f"""You are a portfolio risk analyst. Review these open prediction market positions
and today's news. Provide a brief 2-3 sentence risk narrative.

OPEN POSITIONS:
{position_summary}

TODAY'S NEWS HEADLINES:
{news_summary}

Focus on: any news that materially changes these positions' outlook, concentration risks,
and overall portfolio health. Be concise."""

            narrative = await self._router.call_paid(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )

            if self._discord and narrative:
                await self._discord.send_alert(
                    title="Daily Portfolio Review",
                    description=narrative,
                    color="blue",
                    ping_everyone=False,
                )
        except Exception as exc:
            logger.warning("Portfolio review failed (non-critical): %s", exc)
