"""
FastAPI route handlers for all dashboard endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import settings
from dashboard import db
from dashboard.api.models import (
    BotStatus,
    CalibrationData,
    DailyPnLEntry,
    KillSwitchRequest,
    KillSwitchResponse,
    MarketScanEntry,
    Position,
    PortfolioStats,
    ReliabilityPoint,
    SignalEntry,
    BrierEntry,
)
from forecasting.evidence_gatherer import _compute_days_to_resolution

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_calibrator = None  # Injected by main.py


def set_calibrator(calibrator) -> None:
    global _calibrator
    _calibrator = calibrator


# ---------------------------------------------------------------------------
# Auth dependency for write endpoints
# ---------------------------------------------------------------------------

def verify_auth(authorization: str = Header(default="")) -> None:
    secret = settings.system.dashboard_secret
    expected = f"Bearer {secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=BotStatus)
async def get_status() -> BotStatus:
    risk_state = await db.get_risk_state()
    cal_count = await db.get_calibration_count()
    min_samples = settings.calibration.cold_start_min_samples

    return BotStatus(
        dry_run=settings.system.dry_run,
        kill_switch_active=bool(risk_state.get("kill_switch_active", False)),
        calibration_status="READY" if cal_count >= min_samples else "WARMING_UP",
        calibration_sample_count=cal_count,
        last_scan_at=risk_state.get("last_updated"),
        scan_interval_seconds=settings.system.scan_interval_seconds,
        open_positions=int(risk_state.get("open_position_count", 0)),
        total_exposure_usdc=float(risk_state.get("total_exposure", 0)),
    )


# ---------------------------------------------------------------------------
# GET /api/portfolio
# ---------------------------------------------------------------------------

@router.get("/portfolio", response_model=PortfolioStats)
async def get_portfolio() -> PortfolioStats:
    stats = await db.get_portfolio_stats()
    return PortfolioStats(**stats)


# ---------------------------------------------------------------------------
# GET /api/positions
# ---------------------------------------------------------------------------

@router.get("/positions", response_model=list[Position])
async def get_positions() -> list[Position]:
    positions = await db.get_open_positions()
    result = []
    for p in positions:
        entry_price = p["entry_price"]
        current_price = p["current_market_price"]
        side = p["side"]
        entry_size = p["entry_size"]

        price_diff = (current_price - entry_price) if side == "YES" else (entry_price - current_price)
        unrealized = price_diff * entry_size

        model_est = p.get("model_estimate_at_entry", entry_price)
        divergence_at_entry = abs(model_est - entry_price)

        days = _compute_days_to_resolution(p.get("resolution_date", ""))

        result.append(Position(
            id=p["id"],
            market_condition_id=p["market_condition_id"],
            question=p.get("question"),
            side=side,
            entry_price=entry_price,
            current_market_price=current_price,
            model_estimate_at_entry=model_est,
            divergence_at_entry=divergence_at_entry,
            unrealized_pnl=round(unrealized, 4),
            entry_cost_usdc=p["entry_cost_usdc"],
            entry_timestamp=p["entry_timestamp"],
            resolution_date=p.get("resolution_date"),
            days_to_resolution=days,
            status=p["status"],
            early_exit_flagged=bool(p.get("early_exit_flagged", False)),
            order_id=p.get("order_id"),
        ))

    # Sort: worst unrealized P&L first (see problems first)
    result.sort(key=lambda x: x.unrealized_pnl)
    return result


# ---------------------------------------------------------------------------
# GET /api/positions/{id}
# ---------------------------------------------------------------------------

@router.get("/positions/{position_id}", response_model=dict)
async def get_position_detail(position_id: int) -> dict:
    pos = await db.get_position_by_id(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    # Get associated signal for reasoning chain
    signal_data = None
    if pos.get("signal_id"):
        signals = await db.get_recent_signals(n=100)
        signal_data = next((s for s in signals if s["id"] == pos["signal_id"]), None)

    result = dict(pos)
    if signal_data:
        result["signal_reasoning"] = signal_data.get("reasoning")
        result["signal_evidence_summary"] = signal_data.get("evidence_summary")
        result["signal_news_trigger"] = signal_data.get("news_trigger")
        result["signal_raw_estimates"] = signal_data.get("raw_estimates")

    return result


# ---------------------------------------------------------------------------
# GET /api/signals
# ---------------------------------------------------------------------------

@router.get("/signals", response_model=list[SignalEntry])
async def get_signals(n: int = Query(default=20, ge=1, le=100)) -> list[SignalEntry]:
    signals = await db.get_recent_signals(n=n)
    return [
        SignalEntry(
            id=s["id"],
            market_condition_id=s["market_condition_id"],
            timestamp=s["timestamp"],
            market_price=s["market_price"],
            model_estimate=s["model_estimate"],
            divergence=s["divergence"],
            action=s["action"],
            risk_block_reason=s.get("risk_block_reason"),
            news_trigger=s.get("news_trigger"),
        )
        for s in signals
    ]


# ---------------------------------------------------------------------------
# GET /api/signals/scan — active geo markets sorted by divergence
# ---------------------------------------------------------------------------

@router.get("/signals/scan", response_model=list[MarketScanEntry])
async def get_market_scan() -> list[MarketScanEntry]:
    """
    Returns all active geo markets from DB snapshots, sorted by divergence.
    Note: model_estimate is from last signal if available, else None.
    """
    markets = await db.get_active_markets()
    recent_signals = await db.get_recent_signals(n=500)
    signal_map = {s["market_condition_id"]: s for s in recent_signals}

    result = []
    for m in markets:
        sig = signal_map.get(m["condition_id"])
        model_est = sig["model_estimate"] if sig else None
        divergence = sig["divergence"] if sig else None
        days = _compute_days_to_resolution(m.get("resolution_date", ""))

        result.append(MarketScanEntry(
            condition_id=m["condition_id"],
            question=m["question"],
            market_price_yes=m["market_price_yes"],
            model_estimate=model_est,
            divergence=divergence,
            volume=m.get("volume", 0),
            resolution_date=m.get("resolution_date"),
            days_to_resolution=days,
        ))

    # Sort by divergence descending (highest disagreement first), nulls last
    result.sort(key=lambda x: x.divergence if x.divergence is not None else -1, reverse=True)
    return result


# ---------------------------------------------------------------------------
# GET /api/pnl
# ---------------------------------------------------------------------------

@router.get("/pnl", response_model=list[DailyPnLEntry])
async def get_pnl(range: str = Query(default="7d")) -> list[DailyPnLEntry]:
    days_map = {"7d": 7, "30d": 30, "all": 3650}
    days = days_map.get(range, 7)
    pnl_data = await db.get_daily_pnl(days=days)
    return [DailyPnLEntry(**row) for row in pnl_data]


# ---------------------------------------------------------------------------
# GET /api/calibration
# ---------------------------------------------------------------------------

@router.get("/calibration", response_model=CalibrationData)
async def get_calibration() -> CalibrationData:
    cal_data = await db.get_calibration_data()
    cal_count = len(cal_data)
    min_samples = settings.calibration.cold_start_min_samples

    if cal_count < min_samples or _calibrator is None:
        return CalibrationData(
            status="WARMING_UP",
            sample_count=cal_count,
            current_brier_score=None,
            reliability_diagram=[],
            brier_time_series=[],
        )

    preds = [r["predicted_probability"] for r in cal_data]
    outcomes = [r["actual_outcome"] for r in cal_data]
    current_brier = _calibrator.brier_score(preds[-50:], outcomes[-50:])
    reliability = _calibrator.reliability_diagram_data(preds, outcomes)

    # Build Brier score time series from daily_pnl table
    pnl_data = await db.get_daily_pnl(days=90)
    brier_series = [
        BrierEntry(date=row["date"], brier_score=row["brier_score"], sample_count=0)
        for row in pnl_data
        if row.get("brier_score") is not None
    ]

    return CalibrationData(
        status="READY",
        sample_count=cal_count,
        current_brier_score=round(current_brier, 4),
        reliability_diagram=[ReliabilityPoint(**r) for r in reliability],
        brier_time_series=brier_series,
    )


# ---------------------------------------------------------------------------
# POST /api/kill-switch
# ---------------------------------------------------------------------------

@router.post("/kill-switch", response_model=KillSwitchResponse)
async def toggle_kill_switch(
    body: KillSwitchRequest,
    _auth: None = Depends(verify_auth),
) -> KillSwitchResponse:
    from risk.kill_switch import KillSwitch
    ks = KillSwitch()

    if body.active:
        await ks.activate("Manual activation via dashboard")
        return KillSwitchResponse(active=True, message="Kill switch activated.")
    else:
        await ks.deactivate()
        return KillSwitchResponse(active=False, message="Kill switch deactivated.")
