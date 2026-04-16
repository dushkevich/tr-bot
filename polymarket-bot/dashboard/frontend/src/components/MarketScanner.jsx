export default function MarketScanner({ markets }) {
  function divColor(market) {
    if (!market.divergence) return '#606070'
    if (market.model_estimate > market.market_price_yes) return '#00d4aa'  // YES opportunity
    return '#ff4757'  // NO opportunity
  }

  return (
    <div className="section">
      <div className="section-title">Market Scanner — Fee-Free Geo Markets (55–85%)</div>
      <div className="scroll-container">
        <table>
          <thead>
            <tr>
              <th>Question</th>
              <th>Market Px</th>
              <th>Model Est.</th>
              <th>Divergence</th>
              <th>Volume</th>
              <th>Days Left</th>
            </tr>
          </thead>
          <tbody>
            {(markets || []).map((m, i) => {
              const hasSig = m.model_estimate != null
              return (
                <tr key={m.condition_id || i}>
                  <td style={{ maxWidth: 300 }}>
                    <span title={m.question} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {m.question}
                    </span>
                  </td>
                  <td className="mono">{(m.market_price_yes * 100).toFixed(1)}%</td>
                  <td className="mono" style={{ color: hasSig ? '#a0a0b0' : '#606070' }}>
                    {hasSig ? `${(m.model_estimate * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="mono" style={{ color: divColor(m), fontWeight: m.divergence >= 0.08 ? 700 : 400 }}>
                    {m.divergence != null ? `${(m.divergence * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="mono" style={{ color: '#606070' }}>
                    {m.volume ? `$${(m.volume / 1000).toFixed(0)}k` : '—'}
                  </td>
                  <td className="mono" style={{ color: '#606070' }}>
                    {m.days_to_resolution != null ? m.days_to_resolution.toFixed(0) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
