import { useEffect, useState } from 'react'

export default function TopBar({ status, portfolio }) {
  const [time, setTime] = useState(new Date())
  useEffect(() => { const t = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(t) }, [])

  const ksActive = status?.kill_switch_active
  const dryRun   = status?.dry_run
  const calStatus = status?.calibration_status

  let dotClass = 'active', barStyle = {}
  if (ksActive)       { dotClass = 'killed'; barStyle = { background: '#3a0000' } }
  else if (dryRun)    { barStyle = { background: '#001a3a' } }

  const pnl = portfolio?.total_unrealized_pnl + (portfolio?.total_realized_pnl || 0)
  const pnlColor = !pnl ? '' : pnl >= 0 ? 'green' : 'red'

  const lastScan = status?.last_scan_at
    ? new Date(status.last_scan_at).toLocaleTimeString()
    : '—'

  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 100,
      background: barStyle.background || '#0f0f1e',
      borderBottom: '1px solid #2a2a4a',
      padding: '8px 16px',
      display: 'flex', alignItems: 'center', gap: 24,
    }}>
      <span style={{ fontWeight: 700, fontSize: 14, letterSpacing: '0.05em' }}>
        POLYMARKET BOT
      </span>

      {/* Status */}
      <span>
        <span className={`status-dot ${dotClass}`} />
        <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          {ksActive ? 'KILLED' : dryRun ? 'DRY RUN' : 'LIVE'}
        </span>
      </span>

      {/* Balance */}
      <span>
        <span style={{ fontSize: 10, color: '#a0a0b0', marginRight: 4 }}>BALANCE</span>
        <span className="mono" style={{ fontSize: 15, fontWeight: 700 }}>
          ${(portfolio?.current_balance || 0).toFixed(2)}
        </span>
      </span>

      {/* All-time P&L */}
      <span>
        <span style={{ fontSize: 10, color: '#a0a0b0', marginRight: 4 }}>P&L</span>
        <span className={`mono ${pnlColor}`} style={{ fontSize: 15, fontWeight: 700 }}>
          {pnl >= 0 ? '+' : ''}{(pnl || 0).toFixed(2)}
        </span>
      </span>

      {/* Open positions */}
      <span>
        <span style={{ fontSize: 10, color: '#a0a0b0', marginRight: 4 }}>POSITIONS</span>
        <span className="mono" style={{ fontSize: 13 }}>{status?.open_positions || 0}</span>
      </span>

      {/* Calibration */}
      <span>
        <span style={{ fontSize: 10, color: '#a0a0b0', marginRight: 4 }}>CALIBRATION</span>
        <span style={{ fontSize: 11, color: calStatus === 'READY' ? '#00d4aa' : '#ffa502' }}>
          {calStatus || '—'}
          {calStatus === 'WARMING_UP' && <> ({status?.calibration_sample_count || 0}/20)</>}
        </span>
      </span>

      {/* Last scan */}
      <span style={{ marginLeft: 'auto', fontSize: 10, color: '#606070' }}>
        SCAN {lastScan} · {time.toUTCString().split(' ')[4]} UTC
      </span>
    </div>
  )
}
