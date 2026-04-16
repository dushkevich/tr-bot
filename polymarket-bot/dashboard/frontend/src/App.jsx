import { useEffect, useState, useCallback } from 'react'
import './styles/theme.css'
import TopBar from './components/TopBar'
import PortfolioOverview from './components/PortfolioOverview'
import OpenPositions from './components/OpenPositions'
import SignalFeed from './components/SignalFeed'
import MarketScanner from './components/MarketScanner'
import CalibrationMonitor from './components/CalibrationMonitor'

const POLL_INTERVAL_MS = 30_000

async function fetchJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  return res.json()
}

export default function App() {
  const [status, setStatus]         = useState(null)
  const [portfolio, setPortfolio]   = useState(null)
  const [positions, setPositions]   = useState([])
  const [signals, setSignals]       = useState([])
  const [markets, setMarkets]       = useState([])
  const [pnlData, setPnlData]       = useState([])
  const [calibration, setCalibration] = useState(null)
  const [lastFetch, setLastFetch]   = useState(null)
  const [error, setError]           = useState(null)

  const fetchAll = useCallback(async () => {
    try {
      const [s, p, pos, sig, mkt, pnl, cal] = await Promise.allSettled([
        fetchJSON('/api/status'),
        fetchJSON('/api/portfolio'),
        fetchJSON('/api/positions'),
        fetchJSON('/api/signals?n=20'),
        fetchJSON('/api/signals/scan'),
        fetchJSON('/api/pnl?range=30d'),
        fetchJSON('/api/calibration'),
      ])

      if (s.status === 'fulfilled')   setStatus(s.value)
      if (p.status === 'fulfilled')   setPortfolio(p.value)
      if (pos.status === 'fulfilled') setPositions(pos.value)
      if (sig.status === 'fulfilled') setSignals(sig.value)
      if (mkt.status === 'fulfilled') setMarkets(mkt.value)
      if (pnl.status === 'fulfilled') setPnlData(pnl.value)
      if (cal.status === 'fulfilled') setCalibration(cal.value)

      setLastFetch(new Date())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const t = setInterval(fetchAll, POLL_INTERVAL_MS)
    return () => clearInterval(t)
  }, [fetchAll])

  return (
    <div style={{ minHeight: '100vh', background: '#1a1a2e' }}>
      <TopBar status={status} portfolio={portfolio} />

      {error && (
        <div style={{ margin: '8px 16px', padding: '8px 12px', background: '#3a0000', border: '1px solid #ff4757', borderRadius: 4, color: '#ff4757', fontSize: 11 }}>
          API error: {error}
        </div>
      )}

      <div style={{ paddingTop: 12 }}>
        <PortfolioOverview portfolio={portfolio} pnlData={pnlData} />
        <OpenPositions positions={positions} />
        <SignalFeed signals={signals} />
        <MarketScanner markets={markets} />
        <CalibrationMonitor calibration={calibration} />
      </div>

      <div style={{ textAlign: 'center', padding: '12px 0', color: '#303040', fontSize: 10 }}>
        Last updated: {lastFetch ? lastFetch.toLocaleTimeString() : '—'} · Polling every 30s
      </div>
    </div>
  )
}
