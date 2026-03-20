import { useState, useCallback, useEffect, useMemo } from 'react'
import { PredictionGridCanvas, PredictionStats, Legend } from './SimulationGrid'
import './OfflineView.css'

function formatDateTime(ts) {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric',
    }) + ' ' + d.toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return ts }
}

function ScoreBar({ score, label, color }) {
  return (
    <div className="score-bar-row">
      <span className="score-bar-label">{label}</span>
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${Math.min(score, 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="score-bar-value" style={{ color }}>{score.toFixed(1)}</span>
    </div>
  )
}

function BacktestSeedView({ seedData, seedIndex }) {
  const [view, setView] = useState('prediction') // prediction | ground_truth | both

  if (!seedData) return null

  return (
    <div className="backtest-seed">
      <div className="backtest-seed-header">
        <h4>Seed {seedIndex}</h4>
        <div className="backtest-seed-scores">
          {seedData.obs_score != null && (
            <ScoreBar score={seedData.obs_score} label="Obs+Sim+Prior" color="var(--green)" />
          )}
          {seedData.sim_score != null && (
            <ScoreBar score={seedData.sim_score} label="Sim+Prior" color="var(--papaya)" />
          )}
          {seedData.prior_score != null && (
            <ScoreBar score={seedData.prior_score} label="Prior only" color="var(--grey)" />
          )}
        </div>
        <div className="backtest-seed-meta">
          <span>KL: {seedData.weighted_kl?.toFixed(4)}</span>
          <span>Scored cells: {seedData.scored_cells}</span>
          <span>{seedData.elapsed_s}s</span>
        </div>
      </div>

      <div className="backtest-view-toggle">
        <button
          className={`filter-btn ${view === 'prediction' ? 'active' : ''}`}
          onClick={() => setView('prediction')}
        >Prediction</button>
        <button
          className={`filter-btn ${view === 'ground_truth' ? 'active' : ''}`}
          onClick={() => setView('ground_truth')}
        >Ground Truth</button>
        <button
          className={`filter-btn ${view === 'both' ? 'active' : ''}`}
          onClick={() => setView('both')}
        >Side by Side</button>
      </div>

      <div className="grids-row">
        {(view === 'prediction' || view === 'both') && seedData.prediction && (
          <PredictionGridCanvas
            prediction={seedData.prediction}
            title="Prediction"
          />
        )}
        {(view === 'ground_truth' || view === 'both') && seedData.ground_truth && (
          <PredictionGridCanvas
            prediction={seedData.ground_truth}
            title="Ground Truth"
          />
        )}
      </div>

      <div className="grids-row">
        {(view === 'prediction' || view === 'both') && seedData.prediction && (
          <PredictionStats prediction={seedData.prediction} label="Prediction" />
        )}
        {(view === 'ground_truth' || view === 'both') && seedData.ground_truth && (
          <PredictionStats prediction={seedData.ground_truth} label="Ground Truth" />
        )}
      </div>
    </div>
  )
}

function BacktestDetail({ data }) {
  const [seedIndex, setSeedIndex] = useState(0)

  if (!data || !data.seeds) return null

  const seedData = data.seeds[String(seedIndex)]

  return (
    <div className="simulation-view">
      <div className="backtest-round-header">
        <div className="backtest-round-score">
          <span className="backtest-round-score-value">{data.round_score?.toFixed(1)}</span>
          <span className="backtest-round-score-label">Round {data.round_number} Score</span>
        </div>
        <div className="backtest-round-meta">
          <span>Sims: {data.n_sims}</span>
          <span>{formatDateTime(data.timestamp)}</span>
          {data.config?.label && <span>{data.config.label}</span>}
          {data.config?.sim_weight != null && <span>sim_w={data.config.sim_weight}</span>}
          {data.config?.prior_weight != null && <span>prior_w={data.config.prior_weight}</span>}
        </div>
      </div>

      <div className="backtest-scores-overview">
        {Object.entries(data.seeds).map(([idx, s]) => (
          <div
            key={idx}
            className={`backtest-scores-card ${String(seedIndex) === idx ? 'selected' : ''}`}
            onClick={() => setSeedIndex(Number(idx))}
          >
            <div className="backtest-scores-card-seed">Seed {idx}</div>
            <div className="backtest-scores-card-score">
              {(s.obs_score ?? s.sim_score ?? s.prior_score)?.toFixed(1)}
            </div>
            {s.prior_score != null ? (
              <div className="backtest-scores-card-prior">prior: {s.prior_score?.toFixed(1)}</div>
            ) : (
              <div className="backtest-scores-card-prior"></div>
            )}
          </div>
        ))}
      </div>

      <Legend />

      <BacktestSeedView seedData={seedData} seedIndex={seedIndex} />
    </div>
  )
}

export default function OfflineView({ apiRounds }) {
  const [index, setIndex] = useState(null)
  const [selectedRound, setSelectedRound] = useState(null)
  const [backtestData, setBacktestData] = useState({})
  const [loading, setLoading] = useState(true)

  // Fetch index on mount
  useEffect(() => {
    setLoading(true)
    fetch('/api/offline/index')
      .then(r => r.json())
      .then(setIndex)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const backtests = index?.backtests || []
  const activeFileId = selectedRound || backtests[backtests.length - 1]?.id || backtests[backtests.length - 1]?.round_id
  const activeData = backtestData[activeFileId]

  // Fetch backtest data on demand
  useEffect(() => {
    if (activeFileId && !backtestData[activeFileId]) {
      fetch(`/api/offline/backtests/${activeFileId}`)
        .then(r => r.json())
        .then(data => {
          setBacktestData(prev => ({ ...prev, [activeFileId]: data }))
        })
        .catch(() => {})
    }
  }, [activeFileId, backtestData])

  const entryLabel = useCallback((bt) => {
    const rNum = bt.round_number != null ? `R${bt.round_number}` : bt.round_id?.slice(0, 6)
    const configStr = bt.config?.label || ''
    const score = bt.round_score?.toFixed(1) || '?'
    return `${rNum}${configStr ? ' — ' + configStr : ''} — ${score} pts`
  }, [])

  if (loading) return null

  if (backtests.length === 0) {
    return (
      <>
        <div className="section-header">
          <h2>Offline Backtests</h2>
        </div>
        <div className="empty-state">
          <div className="icon">&#9776;</div>
          <p>No backtests yet. Run <code>python3 offline/run_local.py --backtest</code></p>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="section-header">
        <h2>Offline Backtests</h2>
        <select
          className="round-select"
          value={activeFileId || ''}
          onChange={e => setSelectedRound(e.target.value)}
        >
          {backtests.map(b => (
            <option key={b.id || b.round_id} value={b.id || b.round_id}>
              {entryLabel(b)}
            </option>
          ))}
        </select>
      </div>

      {activeData ? (
        <BacktestDetail data={activeData} />
      ) : (
        <div className="empty-state"><p>Loading backtest data...</p></div>
      )}
    </>
  )
}
