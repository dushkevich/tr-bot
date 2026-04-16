"""
Discord bot main: initializes client, manages channels, dispatches to cogs.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config.settings import settings
from discord_bot import alerts, signals_channel, daily_summary

logger = logging.getLogger(__name__)


class DiscordBot:
    """
    Thin wrapper around discord.py Client.
    Exposes send_* methods used by Pipeline and scheduler.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        self._client = discord.Client(intents=intents)
        self._cfg = settings.discord
        self._ready = False

        @self._client.event
        async def on_ready():
            logger.info("Discord bot connected as %s", self._client.user)
            self._ready = True

    async def start(self, token: str) -> None:
        """Start the Discord bot. Called as a background task."""
        try:
            await self._client.start(token)
        except Exception as exc:
            logger.error("Discord bot failed to start: %s", exc)

    def _get_channel(self, channel_id: int) -> discord.TextChannel | None:
        if not self._ready or not channel_id:
            return None
        return self._client.get_channel(channel_id)

    # ------------------------------------------------------------------
    # Alerts (#alerts channel — red embeds)
    # ------------------------------------------------------------------

    async def send_alert(
        self,
        title: str,
        description: str,
        color: str = "red",
        ping_everyone: bool = False,
    ) -> None:
        channel = self._get_channel(self._cfg.alerts_channel_id)
        if not channel:
            logger.debug("Discord alerts channel not available (id=%d)", self._cfg.alerts_channel_id)
            return

        embed = alerts.build_alert_embed(title, description, color)
        content = "@everyone" if ping_everyone else None
        await channel.send(content=content, embed=embed)

    async def send_kill_switch_activated(self, reason: str) -> None:
        channel = self._get_channel(self._cfg.alerts_channel_id)
        if channel:
            await alerts.send_kill_switch_alert(channel, reason)

    async def send_api_failure(self, service: str, error: str) -> None:
        channel = self._get_channel(self._cfg.alerts_channel_id)
        if channel:
            await alerts.send_api_failure_alert(channel, service, error)

    # ------------------------------------------------------------------
    # Signals (#signals channel — green/gray embeds)
    # ------------------------------------------------------------------

    async def send_trade_executed(self, signal, result) -> None:
        channel = self._get_channel(self._cfg.signals_channel_id)
        if channel:
            await signals_channel.send_trade_executed(channel, signal, result)

    async def send_blocked_signal(self, signal, reason: str) -> None:
        channel = self._get_channel(self._cfg.signals_channel_id)
        if channel:
            await signals_channel.send_blocked_signal(channel, signal, reason)

    async def send_resolution(self, resolution) -> None:
        channel = self._get_channel(self._cfg.signals_channel_id)
        if channel:
            await signals_channel.send_position_closed(channel, resolution, entry_price=0.0)

    # ------------------------------------------------------------------
    # Daily summary (#daily-summary channel)
    # ------------------------------------------------------------------

    async def send_daily_summary(
        self,
        risk_state: dict,
        portfolio_stats: dict,
        today_pnl: dict,
        calibrator=None,
        top_markets: list | None = None,
    ) -> None:
        channel = self._get_channel(self._cfg.summary_channel_id)
        if channel:
            await daily_summary.send_daily_summary(
                channel=channel,
                risk_state=risk_state,
                portfolio_stats=portfolio_stats,
                today_pnl=today_pnl,
                calibrator=calibrator,
                top_markets=top_markets,
            )
