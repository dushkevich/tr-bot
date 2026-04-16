# SPEC: Polymarket AI Geopolitical Trading Bot

## Project overview

Build an AI-powered trading bot for Polymarket that targets **fee-free geopolitical prediction markets** in the 60–80% probability zone. The bot uses multi-model LLM forecasting with real-time news ingestion (GDELT) and statistical calibration (Platt Scaling) to identify markets where the AI's probability estimate diverges significantly from the market price, then executes directional trades.

The system includes a web dashboard for monitoring and a Discord bot for alerts.

---

## Strategy

### Core thesis

Polymarket charges **zero fees on geopolitical/world events markets**. LLMs augmented with real-time search and statistical calibration can achieve a consistent 5–10 percentage point informational edge on these markets, particularly:

- Niche, lower-volume geopolitical markets with fewer sophisticated participants
- Markets where information arrives in non-English languages first (GDELT covers 100+ languages)
- Markets where resolution depends on technical/domain-specific knowledge (regulatory processes, diplomatic protocols)

### Target market profile

- **Category**: Geopolitical, world events (fee-free on Polymarket)
- **Probability zone**: 60–80% (the "sweet spot" where informational edges are most valuable)
- **Minimum liquidity**: Best ask size ≥ 10 shares
- **Must be accepting orders**

### Trading logic

1. Every 15 minutes, GDELT delivers fresh global news
2. **[FREE model]** Pre-filter: keyword + price range filter eliminates ~80% of markets (no LLM needed)
3. **[FREE model]** Match remaining news to active Polymarket geopolitical markets using LLM-based semantic matching (DeepSeek V3.2 or Llama 3.3 70B via OpenRouter free tier)
4. **[FREE model]** Summarize and extract key evidence from matched articles
5. **[PAID model]** One frontier model (Claude Sonnet or DeepSeek R1) estimates probability on the 5–15 filtered markets
6. Apply Platt Scaling calibration to the raw estimate
7. Compare calibrated estimate to current market price
8. If divergence ≥ 8 percentage points AND risk checks pass → execute trade
9. Use FOK (Fill-or-Kill) orders to avoid partial fills

### Supplementary strategy: convergence trading

A low-risk module that scans for markets where the outcome is effectively determined but the price hasn't reached $1.00/$0.00 yet. Buy the near-certain side at $0.95–$0.99, collect $1.00 on resolution. Acts as a capital stabilizer.

### Position management

- Hold positions until resolution for maximum payout, OR
- Sell early if the market moves toward your estimate and you want to free capital
- Monitor whether market has moved toward or away from your model's estimate since entry

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Data Ingestion Layer                   │
│                                                          │
│  GDELT (15-min)    Polymarket APIs     Reddit/X Sentiment│
│  - Articles        - Gamma (markets)   - last30days      │
│  - GKG themes      - CLOB (prices)     - keyword scans   │
│  - Tone scores     - WebSocket (live)                    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  Market Matching Engine                   │
│                                                          │
│  Semantic matching via LLM: connect breaking news to     │
│  active Polymarket geopolitical markets                   │
│  - Extract entities, events, topics from news            │
│  - Match against market questions + resolution criteria  │
│  - Pre-filter: only process fee-free markets in 55-85%   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  AI Forecasting Engine                    │
│                                                          │
│  For each matched market:                                │
│  1. Decompose into sub-questions                         │
│  2. Gather evidence (articles, historical context)       │
│  3. Query 2-3 LLMs independently for probability         │
│  4. Ensemble via trimmed mean                            │
│  5. Apply Platt Scaling calibration                      │
│  6. Output: calibrated probability estimate               │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                     Signal Generator                     │
│                                                          │
│  Compare calibrated estimate vs market price              │
│  If abs(estimate - market_price) ≥ threshold (8 pts):    │
│  → Generate trade signal (BUY YES or BUY NO)             │
│  → Calculate optimal position size (fractional Kelly)    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                      Risk Engine                         │
│                                                          │
│  - Max 5% of portfolio per single market                 │
│  - Max total exposure cap                                │
│  - Daily loss limit → kill switch                        │
│  - Minimum balance threshold                             │
│  - Max open positions count                              │
│  - Brier score monitoring → pause if calibration drifts  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Execution Engine                        │
│                                                          │
│  Place orders via Polymarket CLOB API                     │
│  - FOK (Fill-or-Kill) for immediate execution            │
│  - Respect rate limit: 60 orders/min                     │
│  - Track fills, record positions                         │
│  - Dry-run mode for paper trading                        │
└──────────────────────┬──────────────────────────────────┘
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
    ┌──────────────┐     ┌──────────────┐
    │ Web Dashboard │     │  Discord Bot  │
    │  (FastAPI +   │     │  (Alerts &    │
    │   React)      │     │   Summaries)  │
    └──────────────┘     └──────────────┘
```

---

## Tech stack

### Language & runtime

- **Python 3.11+** — entire backend, pipeline, and bot
- **Node.js** — frontend dashboard only (React)

### Backend framework

- **FastAPI** — API server for dashboard + webhook endpoints
- **SQLite** — all persistent data (signals, trades, P&L, calibration logs, market snapshots)
- **APScheduler** or **Celery with Redis** — scheduled pipeline runs (every 15 min)
- **asyncio** — async CLOB API calls and WebSocket connections

### Frontend

- **React** (single page application)
- **Recharts** or **Chart.js** — P&L charts, calibration diagrams
- **Dark theme** — dense, Bloomberg-terminal-style layout
- **No tabs** — single scrollable page with sections

### Discord

- **discord.py** — bot for alerts and daily summaries

---

## Dependencies & tools (complete list)

### Market data access

| Package | Purpose | Install |
|---------|---------|---------|
| `dr-manhattan` | Unified API for Polymarket + Kalshi + Limitless + Opinion + PredictFun. CCXT-style exchange abstraction with standardized models for markets, orders, orderbooks, positions. Includes WebSocket support and strategy base class. | `pip install dr-manhattan` or clone https://github.com/guzus/dr-manhattan |
| `polymarket-apis` | Feature-rich Polymarket Python client with Pydantic validation. Covers CLOB, Gamma, Data, Web3, WebSocket, and GraphQL APIs. Supports split/merge/redeem CTF operations, reward markets, leaderboard queries. | `pip install polymarket-apis` |
| `py-clob-client` | Official Polymarket CLOB Python client. Order signing (EIP-712), limit orders, market orders, batch orders, position queries, allowance management. | `pip install py-clob-client` |
| `prediction-market-mcp` | MCP server for querying live Polymarket/Kalshi/PredictIt data from Claude Code during development. Not a runtime dependency — a development tool. | Clone https://github.com/JamesANZ/prediction-market-mcp |

### News & OSINT ingestion

| Package | Purpose | Install |
|---------|---------|---------|
| `gdeltdoc` | Python client for GDELT 2.0 Doc API. Article search by keyword/country/language/theme/domain, timeline volume/tone analysis, returns pandas DataFrames. Free, no API key. | `pip install gdeltdoc` |
| `gdeltPyR` | Comprehensive GDELT framework covering Events DB v1/v2, Mentions, and Global Knowledge Graph (GKG). GKG extracts people, organizations, locations, themes, sentiment from every article. | `pip install gdelt` |
| `newsfeed` | Extended GDELT client with continuous querying (splits time ranges into sub-ranges), CLI tool, and full-text article download capability. | `pip install newsfeed` |

**Reference repos for OSINT methodology:**
- `global-activity-monitor` (https://github.com/ashioyajotham/global-activity-monitor) — Geopolitical situation tracker using dual GDELT APIs, TF-IDF summarization, scoring methodology with confidence levels. Study its severity scoring and noise filtering approach.
- `last30days-skill` (https://github.com/mvanhorn/last30days-skill) — Claude Code skill for researching Reddit + X sentiment on any topic from last 30 days. Adapt pattern for monitoring social media discourse around specific markets.

### AI forecasting — tiered model routing (cost-optimized)

The pipeline uses a tiered approach: free/cheap models for classification, matching, and summarization tasks; one paid frontier model only for the final probability estimation on filtered markets. This reduces daily LLM costs from ~$10–25 to ~$0.60–1.70.

**Tier 1: FREE models (matching, summarization, decomposition)**

| Package | Purpose | Install |
|---------|---------|---------|
| `openai` (OpenRouter-compatible) | Single client for all OpenRouter models. OpenRouter API is OpenAI-compatible — just change base_url to `https://openrouter.ai/api/v1`. Access DeepSeek V3.2, Llama 3.3 70B, Qwen3, Mistral Small 3.1, and others for free (rate limited: 20 req/min, 200 req/day) or near-free ($0.25/M tokens for paid tier). | `pip install openai` |
| NVIDIA NIM API | Alternative free inference via build.nvidia.com. OpenAI-compatible API. Hosts Llama, Mistral, DeepSeek. Free for NVIDIA Developer Program members. | `pip install openai` (same client, different base_url) |

**Use free models for:**
- News-to-market semantic matching (~100 calls/day, short prompts)
- Evidence extraction and summarization from GDELT articles
- Question decomposition into sub-questions
- Any classification or filtering task

**Tier 2: PAID frontier model (probability estimation only)**

| Package | Purpose | Install |
|---------|---------|---------|
| `anthropic` | Claude Sonnet for probability estimation — called only on the 5–15 markets that pass all filters. Strong geopolitical reasoning, good calibration after Platt Scaling. | `pip install anthropic` |
| `openai` | DeepSeek R1 via OpenRouter as a cheaper alternative (~$0.55/M input tokens via OpenRouter) with strong reasoning. Or GPT-4o for comparison during calibration phase. | `pip install openai` |

**Use paid model for:**
- Final probability estimation on filtered markets only (5–15 calls/day)
- Optional "portfolio review" — one daily big-context call passing all open positions + today's news

**Tier 3: OPTIONAL local models (zero cost, unlimited)**

If you have a GPU (RTX 3060+ / 8GB+ VRAM), run Llama 3.3 8B or Mistral 7B locally via Ollama for Tier 1 tasks. Eliminates rate limits and data privacy concerns for public data processing. Do NOT use local models for probability estimation — small models are measurably worse at calibrated probabilistic reasoning.

| Package | Purpose | Install |
|---------|---------|---------|
| Ollama | Local model inference server, OpenAI-compatible API at localhost:11434 | https://ollama.com, then `ollama pull llama3.3` |

**Daily cost estimate:**

| Task | Model | Provider | Est. cost/day |
|------|-------|----------|---------------|
| News matching | DeepSeek V3.2 / Llama 3.3 70B | OpenRouter free or NVIDIA NIM | $0.00 |
| Evidence summarization | Same | Same | $0.00 |
| Question decomposition | Same | Same | $0.00 |
| Probability estimation (5–15 markets) | Claude Sonnet or DeepSeek R1 | Anthropic or OpenRouter paid | $0.50–1.50 |
| Portfolio review (1x/day, optional) | Claude Sonnet | Anthropic | $0.10–0.20 |
| **TOTAL** | | | **$0.60–1.70** |

**Calibration & analysis tools:**

| Package | Purpose | Install |
|---------|---------|---------|
| `scikit-learn` | Platt Scaling calibration (LogisticRegression on raw LLM outputs vs outcomes) | `pip install scikit-learn` |
| `numpy` / `pandas` | Numerical operations, data manipulation, Brier score computation | `pip install numpy pandas` |

**Reference repos and papers for forecasting methodology:**
- `forecasterarena` (https://github.com/setrf/forecasterarena) — 7 frontier LLMs competing on Polymarket forecasting. Study their prompting approach and per-category model performance data.
- AIA Forecaster technical report (https://arxiv.org/abs/2511.07678) — Detailed recipe for ensembling, Platt Scaling, and search augmentation. Shows that Platt Scaling is equivalent to generalized log-odds extremization and corrects for LLM's systematic forecast attenuation.
- KalshiBench (https://arxiv.org/abs/2512.16030) — Calibration evaluation methodology. Shows LLMs are systematically overconfident. Their prompt design and evaluation framework are directly applicable.
- ForecastBench (https://forecastingresearch.substack.com) — Dynamic LLM forecasting benchmark with human baselines. Use their difficulty-adjusted Brier score methodology. Current finding: LLMs projected to match superforecasters ~November 2026.
- "Scaling Open-Ended Reasoning" (https://arxiv.org/abs/2512.25070) — Uses global news to synthesize forecasting questions. Key insight: binary yes/no questions are noisy (50% chance even with wrong reasoning), so generate richer sub-questions from news.

### Simulation (optional, phase 3)

| Package | Purpose | Install |
|---------|---------|---------|
| `hermes-geopolitical-market-sim` | OSINT → Polymarket → multi-agent simulation. Counterfactual scenario branches for geopolitical events. | Clone https://github.com/nativ3ai/hermes-geopolitical-market-sim |

### Web dashboard

| Package | Purpose | Install |
|---------|---------|---------|
| `fastapi` | API server | `pip install fastapi` |
| `uvicorn` | ASGI server | `pip install uvicorn` |
| `aiosqlite` | Async SQLite access | `pip install aiosqlite` |
| `react` | Frontend framework | `npx create-react-app dashboard` |
| `recharts` | Charts (P&L, calibration diagrams) | `npm install recharts` |

### Discord bot

| Package | Purpose | Install |
|---------|---------|---------|
| `discord.py` | Discord bot framework | `pip install discord.py` |

### Blockchain / wallet

| Package | Purpose | Install |
|---------|---------|---------|
| `web3` | Polygon wallet operations, allowance setting, balance checks | `pip install web3` |
| `eth-account` | Key management, transaction signing | Included with web3 |

---

## Database schema (SQLite)

```sql
-- Active and historical market snapshots
CREATE TABLE markets (
    id INTEGER PRIMARY KEY,
    condition_id TEXT UNIQUE,
    event_id TEXT,
    question TEXT,
    category TEXT,
    market_price_yes REAL,
    market_price_no REAL,
    volume REAL,
    liquidity REAL,
    neg_risk BOOLEAN,
    fees_enabled BOOLEAN,
    accepting_orders BOOLEAN,
    resolution_date TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    resolution_outcome TEXT,  -- 'YES', 'NO', or NULL
    last_updated TIMESTAMP
);

-- Every signal the pipeline generates (traded or not)
CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    timestamp TIMESTAMP,
    market_price REAL,
    model_estimate REAL,          -- calibrated ensemble estimate
    raw_estimates TEXT,            -- JSON: {"claude": 0.72, "gpt4": 0.78, "gemini": 0.69}
    ensemble_raw REAL,            -- pre-calibration ensemble
    divergence REAL,              -- abs(model_estimate - market_price)
    news_trigger TEXT,            -- summary of what triggered the analysis
    evidence_summary TEXT,        -- condensed evidence used
    reasoning TEXT,               -- LLM reasoning chain
    action TEXT,                  -- 'TRADED', 'BELOW_THRESHOLD', 'RISK_BLOCKED', 'NO_LIQUIDITY'
    risk_block_reason TEXT,       -- if blocked, which rule
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id)
);

-- Executed trades and positions
CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    signal_id INTEGER,
    side TEXT,                    -- 'YES' or 'NO'
    entry_price REAL,
    entry_size REAL,             -- number of shares
    entry_cost_usdc REAL,        -- total USDC spent
    entry_timestamp TIMESTAMP,
    model_estimate_at_entry REAL,
    current_market_price REAL,
    status TEXT,                  -- 'OPEN', 'CLOSED_RESOLVED', 'CLOSED_SOLD'
    exit_price REAL,
    exit_timestamp TIMESTAMP,
    realized_pnl REAL,
    order_id TEXT,
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Daily P&L snapshots
CREATE TABLE daily_pnl (
    date TEXT PRIMARY KEY,
    starting_balance REAL,
    ending_balance REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    trades_opened INTEGER,
    trades_closed INTEGER,
    brier_score REAL              -- rolling calibration metric
);

-- Calibration training data (resolved markets with predictions)
CREATE TABLE calibration_data (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    predicted_probability REAL,   -- what the model said
    actual_outcome INTEGER,       -- 1 = YES resolved, 0 = NO resolved
    timestamp TIMESTAMP,
    category TEXT,
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id)
);

-- Risk state
CREATE TABLE risk_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    daily_pnl REAL DEFAULT 0,
    total_exposure REAL DEFAULT 0,
    open_position_count INTEGER DEFAULT 0,
    current_balance REAL DEFAULT 0,
    kill_switch_active BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMP
);
```

---

## Project structure

```
polymarket-bot/
├── config/
│   ├── settings.py              # All configuration (dataclasses)
│   └── .env                     # API keys (POLY_PRIVATE_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, etc.)
│
├── ingestion/
│   ├── gdelt_client.py          # GDELT news fetching (articles, GKG, tone)
│   ├── market_fetcher.py        # Polymarket market data via Gamma + CLOB
│   ├── sentiment.py             # Reddit/X sentiment scanning (optional)
│   └── matcher.py               # Semantic matching: news ↔ markets via LLM
│
├── forecasting/
│   ├── model_router.py          # Routes tasks to free/paid/local models based on task type
│   ├── decomposer.py            # Break market question into sub-questions [FREE model]
│   ├── evidence_gatherer.py     # Compile evidence package for LLM context [FREE model]
│   ├── llm_forecaster.py        # Query frontier model for probability estimate [PAID model]
│   ├── ensemble.py              # Combine multi-model estimates (if using >1 paid model)
│   └── calibration.py           # Platt Scaling: fit, apply, evaluate, retrain
│
├── signals/
│   ├── signal_generator.py      # Compare calibrated estimate vs market, emit signals
│   └── convergence_scanner.py   # Scan for near-certain markets (supplementary strategy)
│
├── risk/
│   ├── risk_engine.py           # Validate trades against risk rules
│   └── kill_switch.py           # Emergency shutdown logic
│
├── execution/
│   ├── executor.py              # Place/cancel orders via CLOB API
│   ├── position_tracker.py      # Track open positions, unrealized P&L
│   └── wallet.py                # Balance checks, allowance management via web3
│
├── pipeline/
│   ├── main_loop.py             # Orchestrates the full pipeline every 15 min
│   └── scheduler.py             # APScheduler or cron-based scheduling
│
├── dashboard/
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   ├── routes.py            # API endpoints for dashboard data
│   │   └── models.py            # Pydantic response models
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── App.jsx          # Main dashboard layout (single scrollable page)
│   │   │   ├── components/
│   │   │   │   ├── TopBar.jsx           # Fixed: balance, today's P&L, bot status
│   │   │   │   ├── PortfolioOverview.jsx # Money cards + P&L chart
│   │   │   │   ├── OpenPositions.jsx     # Positions table with drill-down
│   │   │   │   ├── SignalFeed.jsx        # Recent signals with action badges
│   │   │   │   ├── MarketScanner.jsx     # Opportunity radar table
│   │   │   │   └── CalibrationMonitor.jsx # Reliability diagram + Brier time series
│   │   │   └── styles/
│   │   │       └── theme.css            # Dark theme, dense layout
│   │   └── package.json
│   └── db.py                    # SQLite connection and query helpers
│
├── discord_bot/
│   ├── bot.py                   # Discord bot main
│   ├── alerts.py                # Immediate alerts (kill switch, losses)
│   ├── signals_channel.py       # Trade executed / signal detected notifications
│   └── daily_summary.py         # End-of-day report
│
├── scripts/
│   ├── setup_allowances.py      # One-time: set USDC + CTF allowances on Polygon
│   ├── build_calibration.py     # Backfill calibration data from resolved markets
│   └── backtest.py              # Run pipeline on historical data to measure edge
│
├── tests/
│   ├── test_matcher.py
│   ├── test_forecasting.py
│   ├── test_calibration.py
│   ├── test_risk.py
│   └── test_execution.py
│
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Dashboard specification

### Layout: single scrollable page, dark theme, no tabs

**Top bar (sticky, always visible)**
- Current USDC balance
- Today's P&L (green if positive, red if negative)
- Bot status indicator: ACTIVE (green dot) / PAUSED (amber dot) / KILLED (red dot)
- Last scan timestamp (shows data freshness)
- If bot is paused or killed, entire top bar background changes to amber/red

**Section 1: Portfolio overview**
- Row of 4 stat cards: Total Invested, Available USDC, All-Time P&L, Win Rate %
- Full-width P&L chart below cards:
  - Bar chart: daily P&L (green/red bars)
  - Line overlay: cumulative P&L
  - Time range selector: 7d / 30d / all

**Section 2: Open positions table**
- Columns: Market Question (truncated, hover for full), Entry Price, Current Price, Model Estimate, Divergence, Unrealized P&L, Days to Resolution, Position Size (USDC)
- Default sort: unrealized P&L ascending (worst first — see problems first)
- Color coding:
  - P&L column: green (profit) / red (loss)
  - Divergence column: blue (market moved toward model = thesis playing out) / orange (market moved away = thesis challenged)
- Click row to expand: shows full reasoning chain (news trigger, individual LLM estimates, calibrated output, decision log)

**Section 3: Recent signals feed**
- Last 20 signals, reverse-chronological
- Each entry: timestamp, market question, model estimate, market price, divergence
- Action badge: TRADED (green), BELOW_THRESHOLD (gray), RISK_BLOCKED (amber), NO_LIQUIDITY (gray)
- Shows what the bot is NOT doing, which is as important as what it IS doing

**Section 4: Market scanner**
- All active fee-free geopolitical markets in the 55–85% zone
- Columns: Question, Market Price, Model Estimate, Divergence, Volume, Days to Resolution
- Sorted by absolute divergence descending (biggest disagreements at top)
- Divergence color: strong green (model says higher → YES opportunity), strong red (model says lower → NO opportunity), gray (small divergence, no opportunity)

**Section 5: Calibration monitor**
- Left: Reliability diagram
  - X-axis: predicted probability (10% buckets)
  - Y-axis: observed outcome frequency
  - Diagonal line = perfect calibration
  - Dot size = number of predictions in each bucket (larger = more data, more trustworthy)
- Right: Brier score time series
  - Rolling 30-day Brier score over time
  - Horizontal threshold line (if Brier exceeds this, calibration is degrading)
  - Optional: breakdown by market category

### Design principles
- Dark gray background (#1a1a2e or similar), not pure black
- Monospaced font for all numbers (alignment in tables)
- Clean sans-serif for labels
- Information density over whitespace — Bloomberg terminal feel, not marketing landing page
- Saturated colors only for actionable data (P&L, status indicators)
- Desktop-first — mobile handled by Discord bot

---

## Discord bot specification

### Three notification tiers, three channels

**#alerts (immediate — things that need attention NOW)**
- Kill switch triggered
- Daily loss limit hit
- Position hit stop-loss
- API connection lost
- Balance dropped below minimum
- Embed color: red

**#signals (timely — bot activity log)**
- New trade executed: market question, side, entry price, model estimate, divergence, position size USDC
- Signal detected but not traded: market, divergence, reason (below threshold / risk blocked / no liquidity)
- Position closed: market, entry vs exit price, realized P&L
- Embed color: green (traded), gray (not traded), blue (informational)

**#daily-summary (once per day, end of trading day)**
- Positions opened/closed today
- Day's realized + unrealized P&L
- Current Brier score (rolling 30-day)
- Total exposure and available capital
- Top 3 opportunities the bot is watching (highest divergence markets)
- Embed color: neutral

### Embed format
- Compact: 5-7 fields max per embed
- Colored sidebar matching tier
- Deep link to relevant position/signal in web dashboard
- No @everyone pings except kill switch triggers

---

## Configuration

All configuration via environment variables and a `settings.py` dataclass:

```python
# .env file

# Wallet
POLY_PRIVATE_KEY=...              # Polymarket wallet private key
POLY_FUNDER_ADDRESS=...           # Polygon wallet address

# LLM APIs — tiered routing
OPENROUTER_API_KEY=...            # OpenRouter (free tier for matching/summarization, paid for DeepSeek R1)
ANTHROPIC_API_KEY=...             # Claude Sonnet (paid, probability estimation only)
NVIDIA_API_KEY=...                # NVIDIA NIM (free alternative to OpenRouter for Tier 1 tasks)

# Model routing config
FREE_MODEL=deepseek/deepseek-chat-v3-0324:free  # OpenRouter free model ID for matching/summarization
PAID_MODEL=anthropic/claude-sonnet-4  # Frontier model for probability estimation via OpenRouter, or use Anthropic directly
USE_LOCAL_OLLAMA=false             # Set true if running local Ollama for free tasks
OLLAMA_BASE_URL=http://localhost:11434/v1

# Discord
DISCORD_BOT_TOKEN=...             # Discord bot token
DISCORD_ALERTS_CHANNEL_ID=...
DISCORD_SIGNALS_CHANNEL_ID=...
DISCORD_SUMMARY_CHANNEL_ID=...

# Trading parameters
DIVERGENCE_THRESHOLD=0.08         # 8 percentage points minimum
MAX_TRADE_SIZE_USDC=50            # Max per single trade
MAX_TOTAL_EXPOSURE_USDC=500       # Max capital deployed
MAX_SINGLE_MARKET_PCT=0.05        # 5% of portfolio per market
MAX_DAILY_LOSS_USDC=50            # Kill switch trigger
MIN_BALANCE_USDC=50               # Kill switch trigger
MAX_OPEN_POSITIONS=20
SCAN_INTERVAL_SECONDS=900         # 15 minutes
DRY_RUN=true                      # Paper trading mode (start here!)

# Calibration
PLATT_SCALING_RETRAIN_DAYS=30     # Retrain calibration model monthly
BRIER_SCORE_PAUSE_THRESHOLD=0.30  # Pause trading if Brier exceeds this
```

---

## Deposit & withdrawal flow

### Funding the bot

```
Bank account (wire/ACH/card)
    ↓
Binance (buy USDC — manual, done by human)
    ↓ withdraw USDC on Polygon network (select native USDC, NOT USDC.e/MATICUSDCE)
Bot wallet (MetaMask on Polygon)
    ↓ run setup_allowances.py once
Polymarket CLOB (trade via API)
```

- Polymarket uses **USDC on Polygon network** exclusively
- **IMPORTANT**: Binance has both native USDC and bridged USDC.e (tickered MATICUSDCE) on Polygon. Polymarket uses **native USDC**. Select the correct one when withdrawing.
- The exchange (Binance) is only a fiat↔USDC on/off-ramp. The bot never interacts with Binance — it only talks to Polymarket via the wallet's private key.
- Gas fees on Polygon: ~$0.007 per transaction (negligible)
- Before first trade: run `setup_allowances.py` to approve USDC and CTF token spending for Polymarket exchange contracts (one-time per wallet)
- API rate limits: 60 orders/minute, 100 public requests/minute

### Withdrawing profits

```
Polymarket wallet (USDC on Polygon)
    ↓ send to your Binance Polygon deposit address (manual)
Binance (sell USDC for fiat — manual)
    ↓
Bank account
```

- No Polymarket platform fees on withdrawal
- Arrives in minutes on Polygon

---

## Development phases

### Phase 1: Data foundation & paper trading
- Set up GDELT ingestion pipeline
- Build market fetcher (Gamma API for market discovery, CLOB for prices)
- Implement semantic matcher (news ↔ markets)
- Build LLM forecasting pipeline (2-3 models)
- Collect historical resolved markets, build calibration dataset
- Implement Platt Scaling calibration
- Run in DRY_RUN mode, log all signals to SQLite
- Measure Brier score for 2-4 weeks
- Build basic dashboard showing signals and calibration

### Phase 2: Live trading with small capital
- Deposit small amount via Binance → Polygon → Polymarket
- Set up wallet allowances
- Switch DRY_RUN=false with strict risk limits
- Deploy Discord bot for alerts
- Start with 5-10 selective trades per week
- Continuously refine calibration with live outcomes
- Monitor Brier score — pause if it degrades

### Phase 3: Scale & expand
- Add convergence trading module
- Increase capital allocation as calibration proves stable
- Consider cross-platform arb (Polymarket vs Kalshi) via dr-manhattan
- Add more market categories as calibration data grows
- Optimize execution with WebSocket for real-time prices
- Add "what-if" simulator panel to dashboard
- Add social media sentiment pipeline (Reddit/X via last30days pattern)

---

## Key technical decisions

### Why SQLite over Postgres
Volume is low (signals every 15 min, 5-10 trades/week). SQLite is zero-configuration, single-file, easy to backup, and more than fast enough. Switch to Postgres only if you need concurrent writes from multiple processes.

### Why FOK orders
Arb-style or directional trades need immediate execution. GTC limit orders risk sitting unfilled while the opportunity evaporates. FOK ensures you either get the price you want or don't trade at all.

### Why tiered model routing instead of 3 paid LLMs
The pipeline has 4 distinct tasks with different quality requirements. Classification, matching, and summarization work fine with free models (DeepSeek V3.2, Llama 3.3 70B). Only probability estimation needs a frontier model. This reduces daily LLM costs from $10–25 to $0.60–1.70, making the bot profitable at much lower capital levels (~$500–800 break-even vs $1,500–2,000 with 3 paid models). The architecture supports upgrading to multi-model ensembling later if calibration data shows it's worth the cost.

### Why OpenRouter as the free model provider
OpenRouter provides a single OpenAI-compatible API for 300+ models. Free tier models (DeepSeek V3.2, Llama 3.3 70B, Mistral Small 3.1) have 200 requests/day limits — sufficient for matching and summarization volume. The API is a drop-in replacement for the OpenAI SDK (change base_url only), so switching models or falling back to NVIDIA NIM requires zero code changes.

### Why Platt Scaling specifically
LLMs systematically attenuate forecasts — they say 65% when they mean 80%. Platt Scaling fits a logistic regression that learns this mapping from historical predictions vs actual outcomes. It's simple, well-understood, and shown effective in the AIA Forecaster research.

### Why 8-point divergence threshold
Below 5 points, you're trading noise. Above 10, opportunities are rare. 8 points balances opportunity frequency against edge quality. This should be tuned based on your observed calibration — if your model is very accurate, you can lower it. If it's noisy, raise it.
