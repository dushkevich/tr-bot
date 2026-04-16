"""
SQLite database layer.
All 6 tables from spec + async aiosqlite query helpers.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

import aiosqlite

from config.settings import settings

logger = logging.getLogger(__name__)

DB_PATH = settings.system.db_path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
-- Active and historical market snapshots
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY,
    condition_id TEXT UNIQUE,
    event_id TEXT,
    question TEXT,
    category TEXT,
    market_price_yes REAL,
    market_price_no REAL,
    volume REAL,
    liquidity REAL,
    neg_risk BOOLEAN DEFAULT FALSE,
    fees_enabled BOOLEAN DEFAULT FALSE,
    accepting_orders BOOLEAN DEFAULT TRUE,
    resolution_date TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    resolution_outcome TEXT,
    last_updated TIMESTAMP
);

-- Every signal the pipeline generates (traded or not)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    timestamp TIMESTAMP,
    market_price REAL,
    model_estimate REAL,
    raw_estimates TEXT,
    ensemble_raw REAL,
    divergence REAL,
    news_trigger TEXT,
    evidence_summary TEXT,
    reasoning TEXT,
    action TEXT,
    risk_block_reason TEXT,
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id)
);

-- Executed trades and open/closed positions
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    signal_id INTEGER,
    side TEXT,
    entry_price REAL,
    entry_size REAL,
    entry_cost_usdc REAL,
    entry_timestamp TIMESTAMP,
    model_estimate_at_entry REAL,
    current_market_price REAL,
    status TEXT DEFAULT 'OPEN',
    exit_price REAL,
    exit_timestamp TIMESTAMP,
    realized_pnl REAL,
    order_id TEXT,
    early_exit_flagged BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- Daily P&L snapshots
CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    starting_balance REAL,
    ending_balance REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    trades_opened INTEGER DEFAULT 0,
    trades_closed INTEGER DEFAULT 0,
    brier_score REAL
);

-- Calibration training data (resolved markets with model predictions)
CREATE TABLE IF NOT EXISTS calibration_data (
    id INTEGER PRIMARY KEY,
    market_condition_id TEXT,
    predicted_probability REAL,
    actual_outcome INTEGER,
    timestamp TIMESTAMP,
    category TEXT,
    FOREIGN KEY (market_condition_id) REFERENCES markets(condition_id)
);

-- Risk state singleton (always id=1)
CREATE TABLE IF NOT EXISTS risk_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    daily_pnl REAL DEFAULT 0,
    total_exposure REAL DEFAULT 0,
    open_position_count INTEGER DEFAULT 0,
    current_balance REAL DEFAULT 0,
    kill_switch_active BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMP
);
"""

_RISK_STATE_INIT = """
INSERT OR IGNORE INTO risk_state (id, daily_pnl, total_exposure, open_position_count,
    current_balance, kill_switch_active, last_updated)
VALUES (1, 0, 0, 0, 0, FALSE, ?);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        yield conn


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create tables and seed risk_state singleton. Safe to call on every startup."""
    async with get_db() as conn:
        await conn.executescript(_SCHEMA)
        await conn.execute(_RISK_STATE_INIT, (_now(),))
        await conn.commit()
    logger.info("Database initialized at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

async def upsert_market(market: dict[str, Any]) -> None:
    sql = """
    INSERT INTO markets (condition_id, event_id, question, category,
        market_price_yes, market_price_no, volume, liquidity,
        neg_risk, fees_enabled, accepting_orders, resolution_date,
        resolved, resolution_outcome, last_updated)
    VALUES (:condition_id, :event_id, :question, :category,
        :market_price_yes, :market_price_no, :volume, :liquidity,
        :neg_risk, :fees_enabled, :accepting_orders, :resolution_date,
        :resolved, :resolution_outcome, :last_updated)
    ON CONFLICT(condition_id) DO UPDATE SET
        market_price_yes=excluded.market_price_yes,
        market_price_no=excluded.market_price_no,
        volume=excluded.volume,
        liquidity=excluded.liquidity,
        accepting_orders=excluded.accepting_orders,
        resolved=excluded.resolved,
        resolution_outcome=excluded.resolution_outcome,
        last_updated=excluded.last_updated
    """
    market.setdefault("last_updated", _now())
    async with get_db() as conn:
        await conn.execute(sql, market)
        await conn.commit()


async def get_active_markets() -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM markets WHERE resolved = FALSE ORDER BY last_updated DESC"
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_resolved_markets_since(since: datetime) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM markets WHERE resolved = TRUE AND last_updated >= ? ORDER BY last_updated DESC",
            (since.isoformat(),),
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

async def record_signal(signal: dict[str, Any]) -> int:
    """Insert signal; raw_estimates dict is JSON-serialized automatically."""
    if isinstance(signal.get("raw_estimates"), dict):
        signal = {**signal, "raw_estimates": json.dumps(signal["raw_estimates"])}
    signal.setdefault("timestamp", _now())
    sql = """
    INSERT INTO signals (market_condition_id, timestamp, market_price, model_estimate,
        raw_estimates, ensemble_raw, divergence, news_trigger, evidence_summary,
        reasoning, action, risk_block_reason)
    VALUES (:market_condition_id, :timestamp, :market_price, :model_estimate,
        :raw_estimates, :ensemble_raw, :divergence, :news_trigger, :evidence_summary,
        :reasoning, :action, :risk_block_reason)
    """
    async with get_db() as conn:
        cursor = await conn.execute(sql, signal)
        await conn.commit()
        return cursor.lastrowid


async def get_recent_signals(n: int = 20) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (n,)
        )
        rows = await cursor.fetchall()
    results = [_row_to_dict(r) for r in rows]
    for r in results:
        if r.get("raw_estimates") and isinstance(r["raw_estimates"], str):
            try:
                r["raw_estimates"] = json.loads(r["raw_estimates"])
            except json.JSONDecodeError:
                pass
    return results


async def get_all_signals_for_market(condition_id: str) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM signals WHERE market_condition_id = ? ORDER BY timestamp DESC",
            (condition_id,),
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

async def record_position(position: dict[str, Any]) -> int:
    position.setdefault("entry_timestamp", _now())
    position.setdefault("status", "OPEN")
    sql = """
    INSERT INTO positions (market_condition_id, signal_id, side,
        entry_price, entry_size, entry_cost_usdc, entry_timestamp,
        model_estimate_at_entry, current_market_price, status, order_id)
    VALUES (:market_condition_id, :signal_id, :side,
        :entry_price, :entry_size, :entry_cost_usdc, :entry_timestamp,
        :model_estimate_at_entry, :current_market_price, :status, :order_id)
    """
    async with get_db() as conn:
        cursor = await conn.execute(sql, position)
        await conn.commit()
        return cursor.lastrowid


async def get_open_positions() -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT p.*, m.question, m.resolution_date FROM positions p "
            "LEFT JOIN markets m ON p.market_condition_id = m.condition_id "
            "WHERE p.status = 'OPEN' ORDER BY p.entry_timestamp DESC"
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_position_by_id(position_id: int) -> dict[str, Any] | None:
    async with get_db() as conn:
        cursor = await conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def get_open_position_for_market(condition_id: str) -> dict[str, Any] | None:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM positions WHERE market_condition_id = ? AND status = 'OPEN' LIMIT 1",
            (condition_id,),
        )
        row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def update_position(position_id: int, updates: dict[str, Any]) -> None:
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["_id"] = position_id
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE positions SET {set_clause} WHERE id = :_id", updates
        )
        await conn.commit()


async def close_position(
    position_id: int, exit_price: float, exit_timestamp: str, realized_pnl: float, reason: str
) -> None:
    status = "CLOSED_RESOLVED" if reason == "resolved" else "CLOSED_SOLD"
    async with get_db() as conn:
        await conn.execute(
            "UPDATE positions SET status=?, exit_price=?, exit_timestamp=?, realized_pnl=? WHERE id=?",
            (status, exit_price, exit_timestamp, realized_pnl, position_id),
        )
        await conn.commit()


# ---------------------------------------------------------------------------
# Daily P&L
# ---------------------------------------------------------------------------

async def upsert_daily_pnl(snapshot: dict[str, Any]) -> None:
    sql = """
    INSERT INTO daily_pnl (date, starting_balance, ending_balance, realized_pnl,
        unrealized_pnl, trades_opened, trades_closed, brier_score)
    VALUES (:date, :starting_balance, :ending_balance, :realized_pnl,
        :unrealized_pnl, :trades_opened, :trades_closed, :brier_score)
    ON CONFLICT(date) DO UPDATE SET
        ending_balance=excluded.ending_balance,
        realized_pnl=excluded.realized_pnl,
        unrealized_pnl=excluded.unrealized_pnl,
        trades_opened=excluded.trades_opened,
        trades_closed=excluded.trades_closed,
        brier_score=excluded.brier_score
    """
    async with get_db() as conn:
        await conn.execute(sql, snapshot)
        await conn.commit()


async def get_daily_pnl(days: int = 30) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?", (days,)
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Calibration data
# ---------------------------------------------------------------------------

async def record_calibration_data(entry: dict[str, Any]) -> None:
    entry.setdefault("timestamp", _now())
    sql = """
    INSERT INTO calibration_data (market_condition_id, predicted_probability,
        actual_outcome, timestamp, category)
    VALUES (:market_condition_id, :predicted_probability, :actual_outcome, :timestamp, :category)
    """
    async with get_db() as conn:
        await conn.execute(sql, entry)
        await conn.commit()


async def get_calibration_data() -> list[dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM calibration_data ORDER BY timestamp DESC"
        )
        rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_calibration_count() -> int:
    async with get_db() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM calibration_data")
        row = await cursor.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Risk state
# ---------------------------------------------------------------------------

async def get_risk_state() -> dict[str, Any]:
    async with get_db() as conn:
        cursor = await conn.execute("SELECT * FROM risk_state WHERE id = 1")
        row = await cursor.fetchone()
    return _row_to_dict(row) if row else {}


async def update_risk_state(updates: dict[str, Any]) -> None:
    updates["last_updated"] = _now()
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE risk_state SET {set_clause} WHERE id = 1", updates
        )
        await conn.commit()


async def set_kill_switch(active: bool) -> None:
    await update_risk_state({"kill_switch_active": active})


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

async def get_portfolio_stats() -> dict[str, Any]:
    """Aggregate stats for dashboard portfolio section."""
    async with get_db() as conn:
        # All-time realized P&L
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions WHERE status != 'OPEN'"
        )
        total_realized = (await cursor.fetchone())[0]

        # Unrealized P&L (sum of open positions based on current_market_price)
        cursor = await conn.execute(
            "SELECT COALESCE(SUM((current_market_price - entry_price) * entry_size), 0) "
            "FROM positions WHERE status = 'OPEN'"
        )
        total_unrealized = (await cursor.fetchone())[0]

        # Win rate
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM positions WHERE status != 'OPEN' AND realized_pnl > 0"
        )
        wins = (await cursor.fetchone())[0]

        cursor = await conn.execute(
            "SELECT COUNT(*) FROM positions WHERE status != 'OPEN'"
        )
        total_closed = (await cursor.fetchone())[0]

        # Total invested (open positions)
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(entry_cost_usdc), 0) FROM positions WHERE status = 'OPEN'"
        )
        total_invested = (await cursor.fetchone())[0]

    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    risk_state = await get_risk_state()

    return {
        "current_balance": risk_state.get("current_balance", 0),
        "total_invested": total_invested,
        "total_realized_pnl": total_realized,
        "total_unrealized_pnl": total_unrealized,
        "all_time_pnl": total_realized + total_unrealized,
        "win_rate": win_rate,
        "total_closed_positions": total_closed,
    }
