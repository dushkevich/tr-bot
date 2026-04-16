import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, LineChart, Line,
} from 'recharts'

export default function CalibrationMonitor({ calibration }) {
  const status = calibration?.status

  if (!calibration || status === 'WARMING_UP') {
    return (
      <div className="section">
        <div className="section-title">Calibration Monitor</div>
        <div className="calibration-warming">
          WARMING UP — {calibration?.sample_count || 0}/20 resolved markets needed
        </div>
      </div>
    )
  }

  const reliability = calibration.reliability_diagram || []
  const brierSeries = calibration.brier_time_series || []

  // Add perfect calibration reference points
  const perfectLine = [{ x: 0, y: 0 }, { x: 1, y: 1 }]

  return (
    <div className="section">
      <div className="section-title">Calibration Monitor</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

        {/* Reliability diagram */}
        <div>
          <div style={{ fontSize: 10, color: '#a0a0b0', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Reliability Diagram
            {calibration.current_brier_score != null && (
              <span style={{ marginLeft: 8, color: calibration.current_brier_score < 0.25 ? '#00d4aa' : '#ff4757' }}>
                Brier: {calibration.current_brier_score.toFixed(4)}
              </span>
            )}
          </div>
          <div style={{ height: 200, background: '#0f0f1a', borderRadius: 4, border: '1px solid #2a2a4a', padding: '8px 0' }}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ left: 8, right: 8, top: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e30" />
                <XAxis
                  dataKey="midpoint" type="number" domain={[0, 1]}
                  tick={{ fontSize: 9, fill: '#606070' }} tickLine={false}
                  label={{ value: 'Predicted', position: 'insideBottom', offset: -2, fill: '#606070', fontSize: 9 }}
                />
                <YAxis
                  dataKey="observed_freq" type="number" domain={[0, 1]}
                  tick={{ fontSize: 9, fill: '#606070' }} tickLine={false} axisLine={false}
                  label={{ value: 'Observed', angle: -90, position: 'insideLeft', fill: '#606070', fontSize: 9 }}
                />
                <Tooltip
                  contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', fontSize: 10 }}
                  formatter={(v, n) => [v.toFixed(3), n]}
                />
                {/* Diagonal perfect calibration line */}
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#2a2a4a" strokeDasharray="4 4" />
                <Scatter
                  data={reliability}
                  fill="#1e90ff"
                  opacity={0.8}
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Brier score time series */}
        <div>
          <div style={{ fontSize: 10, color: '#a0a0b0', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Brier Score (30-day rolling)
          </div>
          <div style={{ height: 200, background: '#0f0f1a', borderRadius: 4, border: '1px solid #2a2a4a', padding: '8px 0' }}>
            {brierSeries.length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#606070', fontSize: 11 }}>
                Not enough data yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={brierSeries} margin={{ left: 8, right: 8, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e1e30" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#606070' }} tickLine={false} />
                  <YAxis domain={[0, 0.5]} tick={{ fontSize: 9, fill: '#606070' }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid #2a2a4a', fontSize: 10 }} />
                  {/* Pause threshold line */}
                  <ReferenceLine y={0.30} stroke="#ff4757" strokeDasharray="4 4" label={{ value: 'Pause', fill: '#ff4757', fontSize: 9 }} />
                  {/* Random baseline */}
                  <ReferenceLine y={0.25} stroke="#ffa502" strokeDasharray="4 4" label={{ value: 'Random', fill: '#ffa502', fontSize: 9 }} />
                  <Line
                    type="monotone" dataKey="brier_score" stroke="#1e90ff"
                    dot={false} strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
