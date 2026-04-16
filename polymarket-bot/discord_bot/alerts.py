"""
Discord #alerts channel: immediate alerts requiring attention NOW.
Red embeds. @everyone ping for kill switch only.
"""
from __future__ import annotations

import discord


def build_alert_embed(title: str, description: str, color: str = "red") -> discord.Embed:
    color_map = {
        "red": discord.Color.from_rgb(255, 71, 87),
        "amber": discord.Color.from_rgb(255, 165, 2),
        "blue": discord.Color.from_rgb(30, 144, 255),
        "green": discord.Color.from_rgb(0, 212, 170),
    }
    embed = discord.Embed(
        title=title,
        description=description,
        color=color_map.get(color, discord.Color.red()),
    )
    return embed


async def send_kill_switch_alert(channel: discord.TextChannel, reason: str) -> None:
    embed = build_alert_embed(
        title="🚨 KILL SWITCH ACTIVATED",
        description=f"**Reason:** {reason}\n\nAll trading has been halted. Deactivate via dashboard POST /api/kill-switch.",
        color="red",
    )
    await channel.send(content="@everyone", embed=embed)


async def send_daily_loss_alert(channel: discord.TextChannel, daily_pnl: float, limit: float) -> None:
    embed = build_alert_embed(
        title="⚠️ Daily Loss Limit Hit",
        description=f"Daily P&L: **${daily_pnl:.2f}** has exceeded limit of **-${limit:.2f}**.\nTrading paused until reset.",
        color="red",
    )
    await channel.send(embed=embed)


async def send_low_balance_alert(channel: discord.TextChannel, balance: float, minimum: float) -> None:
    embed = build_alert_embed(
        title="⚠️ Low Balance Warning",
        description=f"Current balance: **${balance:.2f}** is at or below minimum **${minimum:.2f}**.",
        color="amber",
    )
    await channel.send(embed=embed)


async def send_api_failure_alert(channel: discord.TextChannel, service: str, error: str) -> None:
    embed = build_alert_embed(
        title=f"⚠️ {service} Connection Failed",
        description=f"**Error:** {error}\n\nBot will retry on next cycle.",
        color="amber",
    )
    await channel.send(embed=embed)


async def send_brier_degraded_alert(channel: discord.TextChannel, brier_score: float, threshold: float) -> None:
    embed = build_alert_embed(
        title="⚠️ Calibration Degraded",
        description=(
            f"Brier score **{brier_score:.4f}** exceeds pause threshold **{threshold:.2f}**.\n"
            "Model calibration may be drifting. Trading paused. Review calibration data."
        ),
        color="amber",
    )
    await channel.send(embed=embed)
