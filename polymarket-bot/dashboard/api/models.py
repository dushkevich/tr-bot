"""
Pydantic response models for all FastAPI endpoints.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class BotStatus(BaseModel):
    dry_run: bool
    kill_switch_active: bool
    calibration_status: str  # 'WARMING_UP' | 'READY'
    calibration_sample_count: int
    last_scan_at: str | None
    scan_interval_seconds: int
    open_positions: int
    total_exposure_usdc: float


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class PortfolioStats(BaseModel):
    current_balance: float
    total_invested: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    all_time_pnl: float
    win_rate: float  # 0–100
    total_closed_positions: int


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class Position(BaseModel):
    id: int
    market_condition_id: str
    question: str | None
    side: str
    entry_price: float
    current_market_price: float
    model_estimate_at_entry: float
    divergence_at_entry: float
    unrealized_pnl: float
    entry_cost_usdc: float
    entry_timestamp: str
    resolution_date: str | None
    days_to_resolution: float | None
    status: str
    early_exit_flagged: bool
    order_id: str | None


class PositionDetail(Position):
    """Extended position with full reasoning chain."""
    signal_id: int | None
    signal_reasoning: str | None
    signal_evidence_summary: str | None
    signal_news_trigger: str | None
    signal_raw_estimates: dict[str, float] | None


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SignalEntry(BaseModel):
    id: int
    market_condition_id: str
    timestamp: str
    market_price: float
    model_estimate: float
    divergence: float
    action: str
    risk_block_reason: str | None
    news_trigger: str | None


class MarketScanEntry(BaseModel):
    condition_id: str
    question: str
    market_price_yes: float
    model_estimate: float | None
    divergence: float | None
    volume: float
    resolution_date: str | None
    days_to_resolution: float | None


# ---------------------------------------------------------------------------
# P&L
# ---------------------------------------------------------------------------

class DailyPnLEntry(BaseModel):
    date: str
    starting_balance: float
    ending_balance: float
    realized_pnl: float
    unrealized_pnl: float
    trades_opened: int
    trades_closed: int
    brier_score: float | None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class ReliabilityPoint(BaseModel):
    midpoint: float
    observed_freq: float
    count: int


class BrierEntry(BaseModel):
    date: str
    brier_score: float
    sample_count: int


class CalibrationData(BaseModel):
    status: str  # 'WARMING_UP' | 'READY'
    sample_count: int
    current_brier_score: float | None
    reliability_diagram: list[ReliabilityPoint]
    brier_time_series: list[BrierEntry]


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class KillSwitchRequest(BaseModel):
    active: bool


class KillSwitchResponse(BaseModel):
    active: bool
    message: str
