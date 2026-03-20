// Terrain codes matching the Astar Island spec
// 10=Ocean, 11=Plains, 0=Empty, 1=Settlement, 2=Port, 3=Ruin, 4=Forest, 5=Mountain
//
// This generates a 40x40 example that mimics a realistic Astar Island map:
// ocean borders, fjords, mountain chains, forest patches, and settlements.

function seededRandom(seed) {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff
    return (s >>> 0) / 0xffffffff
  }
}

function generateMap(seed = 42) {
  const W = 40, H = 40
  const rand = seededRandom(seed)
  const grid = Array.from({ length: H }, () => Array(W).fill(11)) // start as plains

  // Ocean border (2 cells thick)
  for (let r = 0; r < H; r++) {
    for (let c = 0; c < W; c++) {
      if (r < 2 || r >= H - 2 || c < 2 || c >= W - 2) {
        grid[r][c] = 10
      }
    }
  }

  // Fjords — cut inland from random edges
  for (let f = 0; f < 4; f++) {
    const side = Math.floor(rand() * 4)
    let r, c, dr, dc
    if (side === 0) { r = 0; c = 5 + Math.floor(rand() * 30); dr = 1; dc = 0 }
    else if (side === 1) { r = H - 1; c = 5 + Math.floor(rand() * 30); dr = -1; dc = 0 }
    else if (side === 2) { r = 5 + Math.floor(rand() * 30); c = 0; dr = 0; dc = 1 }
    else { r = 5 + Math.floor(rand() * 30); c = W - 1; dr = 0; dc = -1 }

    const len = 8 + Math.floor(rand() * 10)
    for (let i = 0; i < len; i++) {
      if (r >= 0 && r < H && c >= 0 && c < W) {
        grid[r][c] = 10
        // widen fjord
        if (dr !== 0 && c + 1 < W) grid[r][c + 1] = 10
        if (dc !== 0 && r + 1 < H) grid[r + 1][c] = 10
      }
      r += dr
      c += dc
      // slight meander
      if (rand() < 0.3) c += dr !== 0 ? (rand() < 0.5 ? 1 : -1) : 0
      if (rand() < 0.3) r += dc !== 0 ? (rand() < 0.5 ? 1 : -1) : 0
      r = Math.max(0, Math.min(H - 1, r))
      c = Math.max(0, Math.min(W - 1, c))
    }
  }

  // Mountain chains — random walks
  for (let m = 0; m < 3; m++) {
    let r = 5 + Math.floor(rand() * 30)
    let c = 5 + Math.floor(rand() * 30)
    const len = 10 + Math.floor(rand() * 15)
    for (let i = 0; i < len; i++) {
      if (r >= 2 && r < H - 2 && c >= 2 && c < W - 2 && grid[r][c] !== 10) {
        grid[r][c] = 5
        // sometimes widen
        if (rand() < 0.4) {
          const nr = r + (rand() < 0.5 ? 1 : -1)
          if (nr >= 2 && nr < H - 2 && grid[nr][c] !== 10) grid[nr][c] = 5
        }
      }
      r += Math.floor(rand() * 3) - 1
      c += Math.floor(rand() * 3) - 1
      r = Math.max(2, Math.min(H - 3, r))
      c = Math.max(2, Math.min(W - 3, c))
    }
  }

  // Forest patches
  for (let f = 0; f < 12; f++) {
    const cr = 4 + Math.floor(rand() * 32)
    const cc = 4 + Math.floor(rand() * 32)
    const size = 3 + Math.floor(rand() * 5)
    for (let dr = -size; dr <= size; dr++) {
      for (let dc = -size; dc <= size; dc++) {
        const r = cr + dr, c = cc + dc
        if (r >= 2 && r < H - 2 && c >= 2 && c < W - 2
            && grid[r][c] === 11 && rand() < 0.55) {
          grid[r][c] = 4
        }
      }
    }
  }

  // Initial settlements — place on plains, spaced apart
  const settlements = []
  for (let attempt = 0; attempt < 200 && settlements.length < 12; attempt++) {
    const r = 4 + Math.floor(rand() * 32)
    const c = 4 + Math.floor(rand() * 32)
    if (grid[r][c] !== 11) continue
    const tooClose = settlements.some(([sr, sc]) =>
      Math.abs(sr - r) + Math.abs(sc - c) < 5
    )
    if (tooClose) continue
    settlements.push([r, c])
    grid[r][c] = 1

    // Check if adjacent to ocean → make it a port
    const adj = [[r-1,c],[r+1,c],[r,c-1],[r,c+1]]
    if (adj.some(([ar, ac]) => ar >= 0 && ar < H && ac >= 0 && ac < W && grid[ar][ac] === 10)) {
      grid[r][c] = 2
    }
  }

  return grid
}

function simulateOutcome(initialGrid, seed = 99) {
  const H = initialGrid.length
  const W = initialGrid[0].length
  const rand = seededRandom(seed)
  const grid = initialGrid.map(row => [...row])

  // Simulate 50 years of change on dynamic cells
  for (let year = 0; year < 50; year++) {
    for (let r = 2; r < H - 2; r++) {
      for (let c = 2; c < W - 2; c++) {
        const cell = grid[r][c]

        // Settlements can become ruins
        if ((cell === 1 || cell === 2) && rand() < 0.03) {
          grid[r][c] = 3
        }

        // Settlements expand to adjacent plains
        if ((cell === 1 || cell === 2) && rand() < 0.02) {
          const dirs = [[r-1,c],[r+1,c],[r,c-1],[r,c+1]]
          for (const [nr, nc] of dirs) {
            if (nr >= 2 && nr < H - 2 && nc >= 2 && nc < W - 2 && grid[nr][nc] === 11) {
              const adjOcean = [[nr-1,nc],[nr+1,nc],[nr,nc-1],[nr,nc+1]]
                .some(([ar, ac]) => ar >= 0 && ar < H && ac >= 0 && ac < W && grid[ar][ac] === 10)
              grid[nr][nc] = adjOcean ? 2 : 1
              break
            }
          }
        }

        // Ruins can be reclaimed by forest or rebuilt
        if (cell === 3) {
          if (rand() < 0.02) grid[r][c] = 4
          else if (rand() < 0.015) grid[r][c] = 1
        }
      }
    }
  }

  return grid
}

export function generateExampleSimulation() {
  const initial = generateMap(42)
  const after = simulateOutcome(initial, 99)
  return { initial, after, width: 40, height: 40 }
}
