import {
  BarChart, Bar, Line, LineChart, ComposedChart, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import { useState } from 'react'

const RANGES = ['7d', '30d', 'all']

export default function PortfolioOverview({ portfolio, pnlData }) {
  const [range, setRange] = useState('7d')

  const stats = [
    { label: 'Total Invested', value: `$${(portfolio?.total_invested || 0).toFixed(2)}` },
    { label: 'Available USDC', value: `$${((portfolio?.current_balance || 0) - (portfolio?.total_invested || 0)).toFixed(2)}` },
    { label: 'All-Time P&L', value: `${(portfolio?.all_time_pnl || 0) >= 0 ? '+' : ''}$${(portfolio?.all_time_pnl || 0).toFixed(2)}`, color: (portfolio?.all_time_pnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Win Rate', value: `${(portfolio?.win_rate || 0).toFixed(1)}%`, color: (portfolio?.win_rate || 0) >= 50 ? 'green' : 'red' },
  ]

  return (
    <div className="section">
      <div className="section-title">Portfolio Overview</div>

      <div className="stat-cards">
        {stats.map(s => (
          <div className="stat-card" key={s.label}>
            <div className="stat-label">{s.label}</div>
            <div className={`stat-value ${s.color || ''}`}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Range selector */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        {RANGES.map(r => (
          <button
            key={r}
            onClick={() => setRange(r)}
            style={{
              padding: '3px 10px', fontSize: 10, cursor: 'pointer',
              background: range === r ? '#1e90ff' : '#1e1e2e',
              color: range === r ? '#fff' : '#a0a0b0',
              border: '1px solid #2a2a4a', borderRadius: 3,
              textTransform: 'uppercase', letterSpacing: '0.05em',
            }}
          >{r}</button>
        ))}
      </div>

      <div style={{ height: 180, background: '#0f0f1a', borderRadius: 4, border: '1px solid #2a2a4a', padding: '8px 0' }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={pnlData || []} margin={{ left: 8, right: 8, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e1e30" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#606070' }} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: '#606070' }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', fontSize: 11 }}
              labelStyle={{ color: '#a0a0b0' }}
            />
            <ReferenceLine y={0} stroke="#2a2a4a" />
            <Bar dataKey="realized_pnl" name="Daily P&L" radius={[2, 2, 0, 0]}>
              {(pnlData || []).map((entry, i) => (
                <Cell key={i} fill={entry.realized_pnl >= 0 ? '#00d4aa' : '#ff4757'} />
              ))}
            </Bar>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
