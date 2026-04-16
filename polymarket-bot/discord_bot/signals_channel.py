"""
Discord #signals channel: bot activity log.
Green embeds for trades, gray for not-traded, blue for informational.
"""
from __future__ import annotations

import discord


def _base_embed(title: str, color: discord.Color) -> discord.Embed:
    return discord.Embed(title=title, color=color)


async def send_trade_executed(
    channel: discord.TextChannel,
    signal,
    result,
    dashboard_url: str = "",
) -> None:
    dry = result.dry_run
    embed = _base_embed(
        title=f"{'[DRY RUN] ' if dry else ''}Trade Executed — {signal.side}",
        color=discord.Color.from_rgb(0, 212, 170),
    )
    embed.add_field(name="Market", value=signal.market.question[:200], inline=False)
    embed.add_field(name="Side", value=signal.side, inline=True)
    embed.add_field(name="Entry Price", value=f"{result.filled_price:.4f}", inline=True)
    embed.add_field(name="Size", value=f"${signal.size_usdc:.2f} USDC", inline=True)
    embed.add_field(name="Model Estimate", value=f"{signal.calibrated_estimate:.3f}", inline=True)
    embed.add_field(name="Market Price", value=f"{signal.market_price:.3f}", inline=True)
    embed.add_field(name="Divergence", value=f"{signal.divergence * 100:.1f}%", inline=True)
    if dashboard_url and result.position_id:
        embed.add_field(name="Dashboard", value=f"{dashboard_url}/positions/{result.position_id}", inline=False)
    await channel.send(embed=embed)


async def send_blocked_signal(
    channel: discord.TextChannel,
    signal,
    reason: str,
) -> None:
    embed = _base_embed(
        title="Signal Not Traded",
        color=discord.Color.from_rgb(80, 80, 96),
    )
    embed.add_field(name="Market", value=signal.market.question[:200], inline=False)
    embed.add_field(name="Model Est.", value=f"{signal.calibrated_estimate:.3f}", inline=True)
    embed.add_field(name="Divergence", value=f"{signal.divergence * 100:.1f}%", inline=True)
    embed.add_field(name="Block Reason", value=reason, inline=True)
    await channel.send(embed=embed)


async def send_position_closed(
    channel: discord.TextChannel,
    resolution,
    entry_price: float,
) -> None:
    pnl = resolution.realized_pnl
    color = discord.Color.from_rgb(0, 212, 170) if pnl >= 0 else discord.Color.from_rgb(255, 71, 87)
    embed = _base_embed(
        title=f"Position Closed — {'WIN' if pnl >= 0 else 'LOSS'}",
        color=color,
    )
    exit_price = 1.0 if resolution.outcome == "YES" else 0.0
    embed.add_field(name="Market", value=resolution.question[:200], inline=False)
    embed.add_field(name="Outcome", value=resolution.outcome, inline=True)
    embed.add_field(name="Entry", value=f"{entry_price:.4f}", inline=True)
    embed.add_field(name="Exit", value=f"{exit_price:.2f}", inline=True)
    embed.add_field(name="Realized P&L", value=f"{'+'if pnl >= 0 else ''}{pnl:.4f} USDC", inline=True)
    await channel.send(embed=embed)
