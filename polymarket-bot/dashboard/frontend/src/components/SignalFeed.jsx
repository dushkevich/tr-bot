export default function SignalFeed({ signals }) {
  function badgeClass(action) {
    if (action === 'TRADED' || action === 'SIGNAL') return 'badge badge-traded'
    if (action === 'RISK_BLOCKED') return 'badge badge-blocked'
    if (action === 'NO_LIQUIDITY') return 'badge badge-no-liq'
    return 'badge badge-below'
  }

  function badgeLabel(action) {
    if (action === 'BELOW_THRESHOLD') return 'BELOW'
    if (action === 'OUTSIDE_ZONE') return 'OUT ZONE'
    return action
  }

  return (
    <div className="section">
      <div className="section-title">Recent Signals (last {signals?.length || 0})</div>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Market</th>
            <th>Market Px</th>
            <th>Model Est.</th>
            <th>Divergence</th>
            <th>Action</th>
            <th>Block Reason</th>
          </tr>
        </thead>
        <tbody>
          {(signals || []).map(s => {
            const time = new Date(s.timestamp).toLocaleTimeString()
            const divPct = (s.divergence * 100).toFixed(1)
            return (
              <tr key={s.id}>
                <td className="mono" style={{ color: '#606070', fontSize: 10 }}>{time}</td>
                <td style={{ maxWidth: 260 }}>
                  <span title={s.news_trigger} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#a0a0b0' }}>
                    {s.news_trigger || s.market_condition_id}
                  </span>
                </td>
                <td className="mono">{s.market_price.toFixed(3)}</td>
                <td className="mono">{s.model_estimate.toFixed(3)}</td>
                <td className="mono" style={{ color: s.divergence >= 0.08 ? '#00d4aa' : '#606070' }}>{divPct}%</td>
                <td><span className={badgeClass(s.action)}>{badgeLabel(s.action)}</span></td>
                <td style={{ color: '#606070', fontSize: 10 }}>{s.risk_block_reason || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
