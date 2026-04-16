# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

An AI-driven geopolitical prediction market trading bot for [Polymarket](https://polymarket.com). It ingests GDELT news, matches articles to open markets using LLMs, generates probability forecasts, applies risk controls, and executes trades on Polygon via the Polymarket CLOB API.

## Environment setup

```bash
# Python dependencies (Python 3.14, venv at .venv/)
pip install -r requirements.txt

# Copy and fill in environment config
cp config/.env.example config/.env   # .env must live in config/ but settings.py loads it from project root
# Actually settings.py loads from: Path(__file__).resolve().parent.parent / ".env"
# So .env must be at polymarket-bot/.env (project root), not inside config/
```

Key `.env` variables to set before running anything real:
- `OPENROUTER_API_KEY` — free-tier LLM calls (matching, summarization, decomposition)
- `ANTHROPIC_API_KEY` — paid Claude Sonnet calls (probability estimation only)
- `POLY_PRIVATE_KEY` / `POLY_FUNDER_ADDRESS` — Polygon wallet for live trading
- `DISCORD_BOT_TOKEN` + channel IDs — optional alerting

## Running the bot

```bash
# Start the main pipeline scheduler (runs every 15 min by default)
python -m pipeline.scheduler

# Start only the dashboard API (FastAPI on port 8000)
python dashboard/api/main.py

# Start dashboard frontend dev server (Vite on port 3000)
cd dashboard/frontend && npm run dev

# Build frontend for production (served by FastAPI as static files)
cd dashboard/frontend && npm run build
```

`DRY_RUN=true` (the default) records signals and simulates trades without placing real orders.

## Running tests

```bash
# All tests
pytest

# Single test file
pytest tests/test_risk.py

# Single test function
pytest tests/test_risk.py::test_daily_loss_exceeded
```

Tests use `asyncio_mode = auto` (configured in `pytest.ini`). All tests mock the LLM router and use a temporary SQLite DB; they do not hit real APIs.

## Utility scripts

```bash
# Backtest: replay stored signals vs resolved markets
python scripts/backtest.py --days 30

# Rebuild Platt calibration model from calibration_data table
python scripts/build_calibration.py

# Approve USDC allowances for Polymarket CLOB (one-time setup for live trading)
python scripts/setup_allowances.py
```

## Architecture

The pipeline runs as a 15-minute `APScheduler` loop orchestrated by `pipeline/scheduler.py`. One cycle (`Pipeline.run_once()` in `pipeline/main_loop.py`) executes these steps in order:

1. **Kill switch check** (`risk/kill_switch.py`) — abort if triggered
2. **GDELT ingestion** (`ingestion/gdelt_client.py`) — fetch geopolitical news articles filtered by theme and tone
3. **Market fetch** (`ingestion/market_fetcher.py`) — fetch open Polymarket markets in the 55–85% price range with geo-category keywords
4. **Semantic matching** (`ingestion/matcher.py`) — batch LLM call (free tier) to pair articles with relevant markets
5. **Question decomposition** (`forecasting/decomposer.py`) — free-model call to break the market question into sub-questions
6. **Evidence gathering** (`forecasting/evidence_gatherer.py`) — free-model call to summarize article evidence per sub-question
7. **Probability estimation** (`forecasting/llm_forecaster.py`) — **paid model** (Claude Sonnet) produces a calibrated probability
8. **Ensemble** (`forecasting/ensemble.py`) — averages multiple estimates (Phase 1: single model, pass-through)
9. **Platt calibration** (`forecasting/calibration.py`) — scikit-learn sigmoid calibration on historical Brier scores; cold-starts at 20 resolved markets
10. **Signal generation** (`signals/signal_generator.py`) — records every signal to DB; fires if divergence ≥ threshold
11. **Risk validation** (`risk/risk_engine.py`) — checks daily loss, exposure limits, position count, balance floor
12. **Execution** (`execution/executor.py`) — places CLOB limit order via `py-clob-client`; no-ops in dry-run mode
13. **Position tracking** (`execution/position_tracker.py`) — refreshes mark prices; flags early-exit candidates
14. **Convergence scanning** (`signals/convergence_scanner.py`) — logged only, not auto-traded in Phase 1

## LLM model routing

`forecasting/model_router.py` implements a two-tier strategy to minimize costs:

| Tier | Tasks | Default model | Fallback |
|------|-------|--------------|---------|
| Free | Matching, decomposition, evidence | OpenRouter free (DeepSeek v3) | NVIDIA NIM (Llama 3.3 70B) or local Ollama |
| Paid | Probability estimation, portfolio review | Claude Sonnet via Anthropic SDK | DeepSeek R1 via OpenRouter |

OpenRouter free tier limits (20 RPM / 200 RPD) are tracked in-process with a sliding window. When the daily limit is hit, the router automatically switches to NVIDIA NIM.

## Database

SQLite at `polymarket_bot.db` (path configurable via `DB_PATH`). All async access goes through `dashboard/db.py` using `aiosqlite` with WAL mode. Six tables:

- `markets` — upserted each cycle, stores price snapshots and resolution state
- `signals` — every pipeline signal (traded or blocked), with raw LLM reasoning
- `positions` — open and closed trades with entry/exit prices and realized P&L
- `daily_pnl` — daily snapshots for the dashboard
- `calibration_data` — resolved market outcomes + model predictions for Platt retraining
- `risk_state` — singleton row (id=1) tracking daily P&L, exposure, kill switch flag

## Configuration

All config lives in `config/settings.py` as Pydantic-style dataclasses, loaded from `.env`. The singleton `settings` object is imported everywhere: `from config.settings import settings`. Key sub-configs: `settings.system`, `settings.trading`, `settings.risk`, `settings.model`, `settings.market`, `settings.discord`.

## Dashboard

React frontend (`dashboard/frontend/src/`) with Recharts. In dev mode, Vite proxies API calls to FastAPI on port 8000. In production, `npm run build` generates `dashboard/frontend/dist/` which FastAPI serves as static files. API routes are defined in `dashboard/api/routes.py`; the kill switch can be toggled via `POST /api/kill-switch` with a bearer token matching `DASHBOARD_SECRET`.
