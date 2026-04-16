import { useState } from 'react'

function pnlColor(v) { return v > 0 ? '#00d4aa' : v < 0 ? '#ff4757' : '#a0a0b0' }

export default function OpenPositions({ positions }) {
  const [expanded, setExpanded] = useState(null)
  const [detail, setDetail]   = useState({})

  async function fetchDetail(id) {
    if (detail[id]) return
    try {
      const res = await fetch(`/api/positions/${id}`)
      const data = await res.json()
      setDetail(d => ({ ...d, [id]: data }))
    } catch {}
  }

  function toggle(id) {
    if (expanded === id) { setExpanded(null) }
    else { setExpanded(id); fetchDetail(id) }
  }

  if (!positions?.length) {
    return (
      <div className="section">
        <div className="section-title">Open Positions</div>
        <div style={{ color: '#606070', fontSize: 12, padding: '12px 0' }}>No open positions.</div>
      </div>
    )
  }

  return (
    <div className="section">
      <div className="section-title">Open Positions ({positions.length})</div>
      <table>
        <thead>
          <tr>
            <th>Market</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Current</th>
            <th>Model Est.</th>
            <th>Divergence</th>
            <th>Unreal. P&L</th>
            <th>Days Left</th>
            <th>Size</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {positions.map(p => {
            const isOpen = expanded === p.id
            const d = detail[p.id]
            const divColor = p.unrealized_pnl >= 0 ? '#1e90ff' : '#ffa502'

            return (
              <>
                <tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => toggle(p.id)}>
                  <td style={{ maxWidth: 280 }}>
                    <span title={p.question} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.early_exit_flagged && <span title="Early exit candidate" style={{ color: '#ffa502', marginRight: 4 }}>⚑</span>}
                      {p.question || p.market_condition_id}
                    </span>
                  </td>
                  <td><span style={{ color: p.side === 'YES' ? '#00d4aa' : '#ff4757', fontWeight: 600, fontSize: 11, fontFamily: 'monospace' }}>{p.side}</span></td>
                  <td className="mono">{p.entry_price.toFixed(3)}</td>
                  <td className="mono">{p.current_market_price.toFixed(3)}</td>
                  <td className="mono" style={{ color: '#a0a0b0' }}>{p.model_estimate_at_entry.toFixed(3)}</td>
                  <td className="mono" style={{ color: divColor }}>{(p.divergence_at_entry * 100).toFixed(1)}%</td>
                  <td className="mono" style={{ color: pnlColor(p.unrealized_pnl) }}>{p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(4)}</td>
                  <td className="mono">{p.days_to_resolution != null ? p.days_to_resolution.toFixed(0) : '—'}</td>
                  <td className="mono">${p.entry_cost_usdc.toFixed(2)}</td>
                  <td style={{ color: '#606070', fontSize: 10 }}>{isOpen ? '▲' : '▼'}</td>
                </tr>
                {isOpen && (
                  <tr key={`${p.id}-detail`}>
                    <td colSpan={10} style={{ background: '#111122', padding: '12px 16px' }}>
                      {d ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                          <div>
                            <div style={{ color: '#606070', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>News Trigger</div>
                            <div style={{ color: '#a0a0b0', fontSize: 11 }}>{d.signal_news_trigger || '—'}</div>
                            <div style={{ color: '#606070', fontSize: 10, textTransform: 'uppercase', marginTop: 10, marginBottom: 4 }}>Evidence Summary</div>
                            <div style={{ color: '#a0a0b0', fontSize: 11, lineHeight: 1.5 }}>{d.signal_evidence_summary || '—'}</div>
                          </div>
                          <div>
                            <div style={{ color: '#606070', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>Reasoning Chain</div>
                            <div className="reasoning-block">{d.signal_reasoning || '—'}</div>
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: '#606070' }}>Loading…</span>
                      )}
                    </td>
                  </tr>
                )}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
