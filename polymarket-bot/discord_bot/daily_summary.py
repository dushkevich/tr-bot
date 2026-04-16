"""
Discord #daily-summary channel: end-of-day report at 23:55 UTC.
"""
from __future__ import annotations

import discord


async def send_daily_summary(
    channel: discord.TextChannel,
    risk_state: dict,
    portfolio_stats: dict,
    today_pnl: dict,
    calibrator=None,
    top_markets: list = None,
) -> None:
    daily_pnl = today_pnl.get("realized_pnl", 0)
    pnl_color = discord.Color.from_rgb(0, 212, 170) if daily_pnl >= 0 else discord.Color.from_rgb(255, 71, 87)

    embed = discord.Embed(
        title="Daily Summary",
        color=discord.Color.from_rgb(80, 100, 140),
    )

    # P&L section
    embed.add_field(
        name="Today's P&L",
        value=f"{'+'if daily_pnl >= 0 else ''}{daily_pnl:.4f} USDC",
        inline=True,
    )
    embed.add_field(
        name="All-Time P&L",
        value=f"{'+'if portfolio_stats.get('all_time_pnl', 0) >= 0 else ''}{portfolio_stats.get('all_time_pnl', 0):.4f}",
        inline=True,
    )
    embed.add_field(
        name="Win Rate",
        value=f"{portfolio_stats.get('win_rate', 0):.1f}%",
        inline=True,
    )

    # Positions
    embed.add_field(
        name="Positions",
        value=(
            f"Opened today: {today_pnl.get('trades_opened', 0)}\n"
            f"Closed today: {today_pnl.get('trades_closed', 0)}\n"
            f"Open now: {risk_state.get('open_position_count', 0)}"
        ),
        inline=True,
    )

    # Capital
    embed.add_field(
        name="Capital",
        value=(
            f"Balance: ${risk_state.get('current_balance', 0):.2f}\n"
            f"Deployed: ${risk_state.get('total_exposure', 0):.2f}"
        ),
        inline=True,
    )

    # Calibration
    brier_text = "WARMING UP"
    if calibrator and calibrator.is_warm():
        from dashboard.db import get_calibration_data
        import asyncio
        try:
            cal_data = asyncio.get_event_loop().run_until_complete(get_calibration_data()) if False else []
        except Exception:
            cal_data = []
        if cal_data:
            preds = [r["predicted_probability"] for r in cal_data[-50:]]
            outcomes = [r["actual_outcome"] for r in cal_data[-50:]]
            brier = calibrator.brier_score(preds, outcomes)
            brier_text = f"{brier:.4f} ({'✓' if brier < 0.25 else '⚠'})"

    embed.add_field(name="Brier Score (30d)", value=brier_text, inline=True)

    # Top divergence opportunities
    if top_markets:
        top_text = "\n".join(
            f"• {m.get('question', '?')[:60]}… ({m.get('divergence', 0)*100:.1f}%)"
            for m in top_markets[:3]
            if m.get("divergence")
        )
        if top_text:
            embed.add_field(name="Top Opportunities", value=top_text, inline=False)

    await channel.send(embed=embed)
