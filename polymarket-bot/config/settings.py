"""
Central configuration for the Polymarket geopolitical trading bot.
All values read from environment variables via python-dotenv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env — check config/ first, then project root
_config_dir = Path(__file__).resolve().parent
_env_path = _config_dir / ".env"
if not _env_path.exists():
    _env_path = _config_dir.parent / ".env"
load_dotenv(_env_path)


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GDELTConfig:
    fetch_interval_minutes: int = int(_optional("GDELT_FETCH_INTERVAL_MINUTES", "60"))
    article_limit: int = int(_optional("GDELT_ARTICLE_LIMIT", "100"))
    # GDELT themes to target for geopolitical relevance
    target_themes: list[str] = field(default_factory=lambda: [
        "CRISISLEX_CRISISLEXREC",
        "CRISISLEX_T01_EARTHQUAKE",
        "POLITICAL",
        "MILITARY",
        "LEADER",
        "ELECTION",
        "DIPLOMATIC",
        "TAX_FNCACT",
        "WB_2281_POLITICAL_STABILITY",
        "WB_471_CONFLICT_AND_VIOLENCE",
    ])
    # Tone threshold: articles with absolute tone above this are considered high-signal
    tone_threshold: float = float(_optional("GDELT_TONE_THRESHOLD", "3.0"))


@dataclass
class MarketConfig:
    # Pre-filter price range — exclude near-certain outcomes
    price_range_min: float = float(_optional("MARKET_PRICE_RANGE_MIN", "0.10"))
    price_range_max: float = float(_optional("MARKET_PRICE_RANGE_MAX", "0.92"))
    # Trading target zone — LLM is the real quality filter
    trading_min: float = float(_optional("MARKET_TRADING_MIN", "0.10"))
    trading_max: float = float(_optional("MARKET_TRADING_MAX", "0.92"))
    # Max days to resolution (0 = no upper limit)
    max_days_to_resolution: int = int(_optional("MAX_DAYS_TO_RESOLUTION", "0"))
    # Minimum liquidity in USDC (applied to liquidity_num field)
    min_liquidity_shares: int = int(_optional("MARKET_MIN_LIQUIDITY_SHARES", "500"))
    # How many markets to fetch per API page
    fetch_limit: int = int(_optional("MARKET_FETCH_LIMIT", "500"))
    # Max pages to fetch (fetch_limit * max_pages = total universe)
    fetch_max_pages: int = int(_optional("MARKET_FETCH_MAX_PAGES", "4"))


@dataclass
class ModelConfig:
    free_model: str = _optional("FREE_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    paid_model: str = _optional("PAID_MODEL", "claude-sonnet-4-6")
    use_local_ollama: bool = _optional("USE_LOCAL_OLLAMA", "false").lower() == "true"
    ollama_base_url: str = _optional("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    # OpenRouter base URL
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # NVIDIA NIM fallback base URL
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"

    # API keys (loaded lazily to allow dry-run without all keys present)
    @property
    def openrouter_api_key(self) -> str:
        return _optional("OPENROUTER_API_KEY", "")

    @property
    def anthropic_api_key(self) -> str:
        return _optional("ANTHROPIC_API_KEY", "")

    @property
    def nvidia_api_key(self) -> str:
        return _optional("NVIDIA_API_KEY", "")

    # Rate limits for OpenRouter free tier
    openrouter_max_rpm: int = 20    # requests per minute
    openrouter_max_rpd: int = 200   # requests per day


@dataclass
class TradingConfig:
    divergence_threshold: float = float(_optional("DIVERGENCE_THRESHOLD", "0.08"))
    max_trade_size_usdc: float = float(_optional("MAX_TRADE_SIZE_USDC", "50"))
    max_total_exposure_usdc: float = float(_optional("MAX_TOTAL_EXPOSURE_USDC", "500"))
    max_single_market_pct: float = float(_optional("MAX_SINGLE_MARKET_PCT", "0.05"))
    # Fractional Kelly multiplier (25% = conservative)
    kelly_fraction: float = float(_optional("KELLY_FRACTION", "0.25"))


@dataclass
class RiskConfig:
    max_daily_loss_usdc: float = float(_optional("MAX_DAILY_LOSS_USDC", "50"))
    min_balance_usdc: float = float(_optional("MIN_BALANCE_USDC", "50"))
    max_open_positions: int = int(_optional("MAX_OPEN_POSITIONS", "20"))
    brier_score_pause_threshold: float = float(_optional("BRIER_SCORE_PAUSE_THRESHOLD", "0.30"))


@dataclass
class CalibrationConfig:
    retrain_days: int = int(_optional("PLATT_SCALING_RETRAIN_DAYS", "30"))
    cold_start_min_samples: int = int(_optional("COLD_START_MIN_SAMPLES", "20"))
    model_path: Path = Path(_optional("CALIBRATION_MODEL_PATH", "models/platt_calibrator.pkl"))


@dataclass
class DiscordConfig:
    bot_token: str = _optional("DISCORD_BOT_TOKEN", "")
    alerts_channel_id: int = int(_optional("DISCORD_ALERTS_CHANNEL_ID", "0"))
    signals_channel_id: int = int(_optional("DISCORD_SIGNALS_CHANNEL_ID", "0"))
    summary_channel_id: int = int(_optional("DISCORD_SUMMARY_CHANNEL_ID", "0"))
    # Daily summary time (UTC)
    daily_summary_hour: int = 23
    daily_summary_minute: int = 55
    # Optional portfolio review time (UTC)
    portfolio_review_hour: int = 9
    portfolio_review_minute: int = 0


@dataclass
class SystemConfig:
    dry_run: bool = _optional("DRY_RUN", "true").lower() == "true"
    scan_interval_seconds: int = int(_optional("SCAN_INTERVAL_SECONDS", "900"))
    balance_refresh_seconds: int = int(_optional("BALANCE_REFRESH_SECONDS", "300"))
    db_path: Path = Path(_optional("DB_PATH", "polymarket_bot.db"))
    dashboard_port: int = int(_optional("DASHBOARD_PORT", "3000"))
    dashboard_api_port: int = int(_optional("DASHBOARD_API_PORT", "8000"))
    dashboard_secret: str = _optional("DASHBOARD_SECRET", "change-me")

    # Wallet
    poly_private_key: str = _optional("POLY_PRIVATE_KEY", "")
    poly_funder_address: str = _optional("POLY_FUNDER_ADDRESS", "")

    # Polygon USDC contract (native USDC, NOT USDC.e)
    usdc_contract_address: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    polygon_rpc_url: str = _optional("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")


# ---------------------------------------------------------------------------
# Top-level settings object
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    gdelt: GDELTConfig = field(default_factory=GDELTConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    system: SystemConfig = field(default_factory=SystemConfig)


# Singleton — import this everywhere
settings = Settings()
