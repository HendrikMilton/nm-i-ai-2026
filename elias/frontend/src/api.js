const BASE = '/astar-island'

async function apiFetch(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`)
  return res.json()
}

export async function fetchRounds() {
  return apiFetch('/rounds')
}

export async function fetchRound(roundId) {
  return apiFetch(`/rounds/${roundId}`)
}

export async function fetchLeaderboard() {
  return apiFetch('/leaderboard')
}
