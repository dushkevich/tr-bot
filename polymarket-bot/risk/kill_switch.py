"""
Kill switch: emergency shutdown logic.
Auto-activates on risk condition breach. Manual deactivation only (via dashboard).
"""
from __future__ import annotations

import logging

from config.settings import settings
from dashboard import db

logger = logging.getLogger(__name__)


class KillSwitch:
    """
    Manages the kill switch state in risk_state table.
    - Activate: sets kill_switch_active=True, sends Discord alert
    - Deactivate: requires human action via POST /api/kill-switch (dashboard)
    - check_conditions: auto-activates if risk thresholds exceeded
    """

    def __init__(self, discord_bot=None) -> None:
        self._discord = discord_bot
        self._cfg = settings.risk

    async def activate(self, reason: str) -> None:
        await db.set_kill_switch(True)
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)
        if self._discord:
            try:
                await self._discord.send_alert(
                    title="KILL SWITCH ACTIVATED",
                    description=reason,
                    color="red",
                    ping_everyone=True,
                )
            except Exception as exc:
                logger.error("Failed to send kill switch Discord alert: %s", exc)

    async def deactivate(self) -> None:
        """
        Deactivate kill switch (human-initiated only).
        Called by POST /api/kill-switch with active=False.
        """
        await db.set_kill_switch(False)
        logger.warning("Kill switch DEACTIVATED by human operator.")
        if self._discord:
            try:
                await self._discord.send_alert(
                    title="Kill Switch Deactivated",
                    description="Kill switch was manually deactivated by operator.",
                    color="amber",
                    ping_everyone=False,
                )
            except Exception as exc:
                logger.error("Failed to send deactivation Discord alert: %s", exc)

    async def check_conditions(self, risk_state: dict) -> None:
        """
        Auto-activate if any kill switch condition is met.
        Called at the end of every pipeline cycle.
        """
        if risk_state.get("kill_switch_active"):
            return  # Already active

        daily_pnl = risk_state.get("daily_pnl", 0)
        balance = risk_state.get("current_balance", 0)

        if daily_pnl <= -self._cfg.max_daily_loss_usdc:
            await self.activate(
                f"Daily loss limit breached: P&L ${daily_pnl:.2f} <= -${self._cfg.max_daily_loss_usdc}"
            )
            return

        if balance <= self._cfg.min_balance_usdc and balance > 0:
            await self.activate(
                f"Minimum balance breached: ${balance:.2f} <= ${self._cfg.min_balance_usdc}"
            )
            return

    async def is_active(self) -> bool:
        risk_state = await db.get_risk_state()
        return bool(risk_state.get("kill_switch_active", False))
