import { useState, useCallback, useMemo, useEffect } from 'react'
import SimulationGrid, { GridCanvas, Legend, TerrainStats, PredictionGridCanvas, PredictionStats } from './SimulationGrid'
import { generateExampleSimulation } from './exampleSimulation'
import { fetchRounds } from './api'
import './App.css'

// --- Helpers ---

function getBadgeClass(action) {
  if (action.startsWith('simulate')) return 'simulate'
  if (action.startsWith('submit')) return 'submit'
  if (action.startsWith('fetch') || action.startsWith('start')) return 'fetch'
  if (action.startsWith('check') || action.startsWith('plan')) return 'check'
  return ''
}

function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}

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

function roundLabel(id, apiRounds) {
  const r = (apiRounds || []).find(r => r.id === id)
  if (r?.round_number != null) return `Round ${r.round_number}`
  return id.length > 12 ? id.slice(0, 8) + '...' : id
}

function buildMapFromQueries(queries, seedIndex, mapW, mapH) {
  const grid = Array.from({ length: mapH }, () => Array(mapW).fill(null))
  const viewports = []

  for (const q of queries) {
    if (q.seed_index !== seedIndex) continue
    const vp = q.viewport
    viewports.push(vp)
    if (!q.grid || q.grid.length === 0) continue

    for (let r = 0; r < q.grid.length; r++) {
      for (let c = 0; c < q.grid[r].length; c++) {
        const mapR = vp.y + r
        const mapC = vp.x + c
        if (mapR >= 0 && mapR < mapH && mapC >= 0 && mapC < mapW) {
          grid[mapR][mapC] = q.grid[r][c]
        }
      }
    }
  }

  return { grid, viewports }
}

function timeRemaining(endTs) {
  const now = Date.now()
  const end = new Date(endTs).getTime()
  const diff = end - now
  if (diff <= 0) return 'Ended'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (h > 0) return `${h}h ${m}m remaining`
  return `${m}m remaining`
}

// --- Status badge ---

function StatusBadge({ status }) {
  const cls = {
    active: 'status-active',
    pending: 'status-pending',
    scoring: 'status-scoring',
    completed: 'status-completed',
  }[status] || ''

  return <span className={`status-badge ${cls}`}>{status}</span>
}

// --- Current Round Banner ---

function CurrentRoundBanner({ rounds }) {
  const active = rounds.find(r => r.status === 'active')
  const latest = active || rounds[rounds.length - 1]

  if (!latest) return null

  return (
    <div className={`round-banner ${active ? 'round-banner-active' : ''}`}>
      <div className="round-banner-top">
        <StatusBadge status={latest.status} />
        <span className="round-banner-id">
          {latest.round_number != null ? `Round ${latest.round_number}` : latest.id}
        </span>
      </div>
      <div className="round-banner-details">
        {latest.start_time && (
          <span>Started: {formatDateTime(latest.start_time)}</span>
        )}
        {latest.end_time && (
          <span>
            {latest.status === 'active'
              ? timeRemaining(latest.end_time)
              : `Ended: ${formatDateTime(latest.end_time)}`}
          </span>
        )}
        {latest.map_width && latest.map_height && (
          <span>Map: {latest.map_width}x{latest.map_height}</span>
        )}
        {latest.num_seeds != null && (
          <span>Seeds: {latest.num_seeds}</span>
        )}
      </div>
    </div>
  )
}

// --- Rounds List ---

function RoundsList({ rounds }) {
  if (!rounds || rounds.length === 0) return null

  return (
    <div className="rounds-list">
      <h3 className="rounds-list-title">All Rounds</h3>
      {[...rounds].reverse().map(r => (
        <div key={r.id} className="rounds-list-item">
          <StatusBadge status={r.status} />
          <span className="rounds-list-id">
            {r.round_number != null ? `Round ${r.round_number}` : r.id.slice(0, 8)}
          </span>
          {r.start_time && (
            <span className="rounds-list-time">{formatDateTime(r.start_time)}</span>
          )}
        </div>
      ))}
    </div>
  )
}

// --- LogEntry ---

function LogEntry({ entry }) {
  const [expanded, setExpanded] = useState(false)
  const badge = getBadgeClass(entry.action)

  return (
    <div
      className={`log-entry ${expanded ? 'expanded' : ''}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="log-entry-header">
        <span className={`log-badge ${badge}`}>{entry.action}</span>
        <span className="log-time">{formatTime(entry.timestamp)}</span>
      </div>
      {expanded && (
        <div className="log-details">
          <pre>{JSON.stringify(entry.details || {}, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

// --- Logs View ---

function LogsView({ logData, fetchRoundLog, apiRounds }) {
  const [selectedRound, setSelectedRound] = useState(null)
  const roundIds = (logData?.index?.rounds || []).map(r => r.id)

  const activeRound = selectedRound || roundIds[roundIds.length - 1]
  const round = logData?.rounds?.[activeRound]

  // Fetch round data when selection changes
  useEffect(() => {
    if (activeRound && !logData?.rounds?.[activeRound]) {
      fetchRoundLog(activeRound)
    }
  }, [activeRound, logData?.rounds, fetchRoundLog])

  if (roundIds.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">&#9776;</div>
        <p>No round logs available. Run the pipeline first.</p>
      </div>
    )
  }

  const allEntries = []
  if (round) {
    for (const a of (round.actions || [])) {
      allEntries.push({ ...a, _type: 'action' })
    }
    for (const q of (round.queries || [])) {
      allEntries.push({
        timestamp: q.timestamp,
        action: 'simulate',
        details: { seed_index: q.seed_index, viewport: q.viewport, budget_remaining: q.budget_remaining },
        _type: 'query',
      })
    }
    for (const s of (round.submissions || [])) {
      allEntries.push({
        timestamp: s.timestamp,
        action: 'submit_prediction',
        details: { seed_index: s.seed_index },
        _type: 'submission',
      })
    }
    allEntries.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
  }

  const queryCount = round?.queries?.length || 0
  const subCount = round?.submissions?.length || 0

  return (
    <>
      <div className="section-header">
        <h2>Run Logs</h2>
        <RoundSelector
          roundIds={roundIds}
          selected={activeRound}
          onSelect={setSelectedRound}
          apiRounds={apiRounds}
        />
      </div>

      <div className="stats-bar">
        <div className="stat-card">
          <div className="value">{allEntries.length}</div>
          <div className="label">Total Events</div>
        </div>
        <div className="stat-card">
          <div className="value">{queryCount}<span className="stat-max">/50</span></div>
          <div className="label">Queries Used</div>
        </div>
        <div className="stat-card">
          <div className="value">{subCount}<span className="stat-max">/5</span></div>
          <div className="label">Submissions</div>
        </div>
      </div>

      <div className="log-list">
        {allEntries.map((entry, i) => (
          <LogEntry key={i} entry={entry} />
        ))}
      </div>
    </>
  )
}

// --- Round Selector ---

function RoundSelector({ roundIds, selected, onSelect, apiRounds }) {
  return (
    <select
      className="round-select"
      value={selected || ''}
      onChange={e => onSelect(e.target.value)}
    >
      {roundIds.map(id => (
        <option key={id} value={id}>{roundLabel(id, apiRounds)}</option>
      ))}
    </select>
  )
}

// --- Simulation View ---

function RoundSimulationView({ round }) {
  const [seedIndex, setSeedIndex] = useState(0)
  const mapW = round.map_width || 40
  const mapH = round.map_height || 40

  const { grid, viewports } = useMemo(
    () => buildMapFromQueries(round.queries || [], seedIndex, mapW, mapH),
    [round.queries, seedIndex, mapW, mapH]
  )

  const seedQueries = (round.queries || []).filter(q => q.seed_index === seedIndex)
  const seedSubmission = (round.submissions || []).find(s => s.seed_index === seedIndex)

  // Extract prediction tensor from build_prediction action
  const seedPrediction = useMemo(() => {
    const action = (round.actions || []).find(
      a => a.action === 'build_prediction' && a.details?.seed_index === seedIndex
    )
    return action?.details?.prediction || null
  }, [round.actions, seedIndex])

  const seedsWithData = useMemo(() => {
    const seeds = new Set()
    for (const q of (round.queries || [])) seeds.add(q.seed_index)
    return seeds
  }, [round.queries])

  return (
    <div className="simulation-view">
      <div className="seed-tabs">
        {[0, 1, 2, 3, 4].map(s => (
          <button
            key={s}
            className={`seed-btn ${seedIndex === s ? 'active' : ''} ${seedsWithData.has(s) ? '' : 'empty'}`}
            onClick={() => setSeedIndex(s)}
          >
            Seed {s}
            {seedsWithData.has(s) && (
              <span className="seed-count">
                {(round.queries || []).filter(q => q.seed_index === s).length}q
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="seed-info-bar">
        <span>{seedQueries.length} queries</span>
        <span className="seed-info-sep" />
        <span>{seedSubmission ? 'Submitted' : 'Not submitted'}</span>
        {seedPrediction && (
          <>
            <span className="seed-info-sep" />
            <span>Prediction logged</span>
          </>
        )}
      </div>

      <Legend />

      <div className="grids-row">
        <GridCanvas
          grid={grid}
          title={`Seed ${seedIndex} — Observed`}
          viewportOverlays={viewports}
        />
        {seedPrediction && (
          <PredictionGridCanvas
            prediction={seedPrediction}
            title={`Seed ${seedIndex} — Prediction`}
          />
        )}
      </div>

      <div className="grids-row">
        <TerrainStats grid={grid} label="Observed Terrain" />
        {seedPrediction && (
          <PredictionStats prediction={seedPrediction} label="Predicted Terrain" />
        )}
      </div>
    </div>
  )
}

function SimulationView({ logData, fetchRoundLog, apiRounds }) {
  const [selectedRound, setSelectedRound] = useState(null)
  const roundIds = (logData?.index?.rounds || []).map(r => r.id)
  const activeRound = selectedRound || roundIds[roundIds.length - 1]
  const round = logData?.rounds?.[activeRound]

  // Fetch round data when selection changes
  useEffect(() => {
    if (activeRound && !logData?.rounds?.[activeRound]) {
      fetchRoundLog(activeRound)
    }
  }, [activeRound, logData?.rounds, fetchRoundLog])

  const hasRounds = roundIds.length > 0 && round && (round.queries || []).length > 0

  const exampleData = useMemo(() => {
    if (hasRounds) return null
    return generateExampleSimulation()
  }, [hasRounds])

  return (
    <>
      <div className="section-header">
        <h2>Simulation Visualizer</h2>
        {roundIds.length > 0 ? (
          <RoundSelector
            roundIds={roundIds}
            selected={activeRound}
            onSelect={setSelectedRound}
            apiRounds={apiRounds}
          />
        ) : (
          <span className="section-subtitle">Example 40x40 map — seed 42</span>
        )}
      </div>

      {hasRounds ? (
        <RoundSimulationView round={round} />
      ) : round && !round.queries?.length ? (
        <div className="empty-state"><p>No queries logged for this round yet.</p></div>
      ) : (
        <SimulationGrid data={exampleData} />
      )}
    </>
  )
}

// --- App ---

function App() {
  const [tab, setTab] = useState('rounds')
  const [logData, setLogData] = useState(null)
  const [rounds, setRounds] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Fetch log index (lightweight — just round IDs)
  const doFetchLogIndex = useCallback(async () => {
    try {
      const res = await fetch('/api/logs/index')
      if (!res.ok) return
      const data = await res.json()
      setLogData(prev => ({ ...prev, index: data }))
    } catch {
      // silently ignore poll failures
    }
  }, [])

  // Fetch a specific round's full log data (on demand)
  const fetchRoundLog = useCallback(async (roundId) => {
    try {
      const res = await fetch(`/api/logs/rounds/${roundId}`)
      if (!res.ok) return null
      const data = await res.json()
      setLogData(prev => ({
        ...prev,
        rounds: { ...(prev?.rounds || {}), [roundId]: data },
      }))
      return data
    } catch {
      return null
    }
  }, [])

  const doFetchRounds = useCallback(async () => {
    try {
      const data = await fetchRounds()
      setRounds(data)
    } catch {
      // silently ignore poll failures
    }
  }, [])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    await Promise.all([doFetchLogIndex(), doFetchRounds()])
    setLoading(false)
  }, [doFetchLogIndex, doFetchRounds])

  // Fetch on mount
  useEffect(() => { refreshAll() }, [refreshAll])

  return (
    <div className="app">
      <header className="header">
        <h1>ASTAR ISLAND</h1>
        <nav className="tabs">
          <button
            className={`tab-btn ${tab === 'rounds' ? 'active' : ''}`}
            onClick={() => setTab('rounds')}
          >
            Rounds
          </button>
          <button
            className={`tab-btn ${tab === 'simulation' ? 'active' : ''}`}
            onClick={() => setTab('simulation')}
          >
            Simulation
          </button>
          <button
            className={`tab-btn ${tab === 'logs' ? 'active' : ''}`}
            onClick={() => setTab('logs')}
          >
            Run Logs
          </button>
          <button className="fetch-btn" onClick={refreshAll} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </nav>
      </header>

      <main className="main">
        {error && <div className="error-banner">{error}</div>}

        {tab === 'rounds' && (
          <>
            <div className="section-header">
              <h2>Current Round</h2>
            </div>
            {rounds.length > 0 ? (
              <>
                <CurrentRoundBanner rounds={rounds} />
                <RoundsList rounds={rounds} />
              </>
            ) : !loading ? (
              <div className="empty-state">
                <div className="icon">&#9776;</div>
                <p>No rounds available.</p>
              </div>
            ) : null}
          </>
        )}

        {tab === 'simulation' && <SimulationView logData={logData} fetchRoundLog={fetchRoundLog} apiRounds={rounds} />}
        {tab === 'logs' && <LogsView logData={logData} fetchRoundLog={fetchRoundLog} apiRounds={rounds} />}
      </main>
    </div>
  )
}

export default App
