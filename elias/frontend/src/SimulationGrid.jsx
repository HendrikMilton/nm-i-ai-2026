import { useMemo } from 'react'
import './SimulationGrid.css'

// Colors matched from official Astar Island docs
export const TERRAIN_COLORS = {
  0:  '#1E3448', // Empty
  10: '#2B5278', // Ocean
  11: '#C8B87C', // Plains
  1:  '#D4852A', // Settlement
  2:  '#2A8C8C', // Port
  3:  '#8C2A2A', // Ruin
  4:  '#3D7C3F', // Forest
  5:  '#7C7C8A', // Mountain
  unobserved: '#0D0D0D',
}

const TERRAIN_LABELS = {
  10: 'Ocean',
  11: 'Plains',
  0:  'Empty',
  1:  'Settlement',
  2:  'Port',
  3:  'Ruin',
  4:  'Forest',
  5:  'Mountain',
}

export function GridCanvas({ grid, title, viewportOverlays }) {
  const height = grid.length
  const width = grid[0].length
  const cellSize = Math.max(8, Math.min(14, Math.floor(560 / Math.max(width, height))))

  const cells = useMemo(() => {
    const result = []
    for (let r = 0; r < height; r++) {
      for (let c = 0; c < width; c++) {
        const val = grid[r][c]
        const fill = val === null
          ? TERRAIN_COLORS.unobserved
          : (TERRAIN_COLORS[val] || TERRAIN_COLORS[0])
        result.push(
          <rect
            key={`${r}-${c}`}
            x={c * cellSize}
            y={r * cellSize}
            width={cellSize}
            height={cellSize}
            fill={fill}
          />
        )
      }
    }
    return result
  }, [grid, cellSize, width, height])

  const overlays = useMemo(() => {
    if (!viewportOverlays) return null
    return viewportOverlays.map((vp, i) => (
      <rect
        key={`vp-${i}`}
        x={vp.x * cellSize}
        y={vp.y * cellSize}
        width={vp.w * cellSize}
        height={vp.h * cellSize}
        fill="none"
        stroke="var(--papaya)"
        strokeWidth="1"
        strokeOpacity="0.5"
      />
    ))
  }, [viewportOverlays, cellSize])

  return (
    <div className="grid-panel">
      {title && <h3 className="grid-title">{title}</h3>}
      <svg
        width={width * cellSize}
        height={height * cellSize}
        className="grid-svg"
      >
        {cells}
        {overlays}
      </svg>
    </div>
  )
}

export function Legend() {
  const entries = [
    [10, 'Ocean (class 0)'],
    [11, 'Plains (class 0)'],
    [4,  'Forest (class 4)'],
    [5,  'Mountain (class 5)'],
    [1,  'Settlement (class 1)'],
    [2,  'Port (class 2)'],
    [3,  'Ruin (class 3)'],
    ['unobserved', 'Unobserved'],
  ]

  return (
    <div className="legend">
      {entries.map(([code, label]) => (
        <div key={code} className="legend-item">
          <span
            className="legend-swatch"
            style={{ backgroundColor: TERRAIN_COLORS[code] }}
          />
          <span className="legend-label">{label}</span>
        </div>
      ))}
    </div>
  )
}

export function TerrainStats({ grid, label }) {
  const counts = {}
  let unobserved = 0
  for (const row of grid) {
    for (const cell of row) {
      if (cell === null) { unobserved++; continue }
      counts[cell] = (counts[cell] || 0) + 1
    }
  }
  const total = grid.length * grid[0].length

  const entries = Object.entries(counts)
    .map(([code, count]) => ({
      code: Number(code),
      label: TERRAIN_LABELS[Number(code)] || `Code ${code}`,
      count,
      pct: ((count / total) * 100).toFixed(1),
      color: TERRAIN_COLORS[Number(code)] || TERRAIN_COLORS[0],
    }))
    .sort((a, b) => b.count - a.count)

  if (unobserved > 0) {
    entries.push({
      code: 'unobserved',
      label: 'Unobserved',
      count: unobserved,
      pct: ((unobserved / total) * 100).toFixed(1),
      color: TERRAIN_COLORS.unobserved,
    })
  }

  return (
    <div className="terrain-stats">
      <h4>{label}</h4>
      <div className="stats-rows">
        {entries.map(e => (
          <div key={e.code} className="stats-row">
            <span className="legend-swatch" style={{ backgroundColor: e.color }} />
            <span className="stats-name">{e.label}</span>
            <span className="stats-count">{e.count}</span>
            <div className="stats-bar-outer">
              <div
                className="stats-bar-inner"
                style={{ width: `${e.pct}%`, backgroundColor: e.color }}
              />
            </div>
            <span className="stats-pct">{e.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// Legacy: example simulation with initial/after grids
export default function SimulationGrid({ data }) {
  if (!data) return null

  return (
    <div className="simulation-view">
      <Legend />
      <div className="grids-row">
        <GridCanvas grid={data.initial} title="Initial State" />
        <GridCanvas grid={data.after} title="After 50 Years" />
      </div>
      <div className="grids-row">
        <TerrainStats grid={data.initial} label="Initial State" />
        <TerrainStats grid={data.after} label="After 50 Years" />
      </div>
    </div>
  )
}
