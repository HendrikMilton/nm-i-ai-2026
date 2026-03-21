const COOKIE = 'access_token=REDACTED_TOKEN';
const BASE = 'https://api.ainm.no/astar-island';
const HEADERS = {
  'accept': '*/*',
  'origin': 'https://app.ainm.no',
  'referer': 'https://app.ainm.no/',
  'cookie': COOKIE,
};

const TERRAIN_TO_CLASS: Record<number, number> = {
  0: 0, 10: 0, 11: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5,
};
const N_CLASSES = 6;
const GRID_SIZE = 40;

async function api(path: string) {
  const res = await fetch(`${BASE}${path}`, { headers: HEADERS });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json();
}

/**
 * Reconstruct observation fields from v2_R query viewport grids.
 * Returns { observed_counts, observed_probs, n_observations } per seed.
 */
function reconstructObservations(queries: any[]): {
  observed_counts: number[][][];
  observed_probs: number[][][];
  n_observations: number[][];
} {
  const obs_counts = Array.from({ length: GRID_SIZE }, () =>
    Array.from({ length: GRID_SIZE }, () => new Array(N_CLASSES).fill(0))
  );
  const n_obs = Array.from({ length: GRID_SIZE }, () =>
    new Array(GRID_SIZE).fill(0)
  );

  for (const q of queries) {
    const vp = q.viewport;
    const grid = q.grid;
    if (!vp || !grid) continue;
    const { x, y, w, h } = vp;
    for (let dr = 0; dr < Math.min(h, grid.length); dr++) {
      for (let dc = 0; dc < Math.min(w, grid[dr]?.length ?? 0); dc++) {
        const r = y + dr;
        const c = x + dc;
        if (r >= 0 && r < GRID_SIZE && c >= 0 && c < GRID_SIZE) {
          const code = grid[dr][dc];
          const cls = TERRAIN_TO_CLASS[code] ?? 0;
          obs_counts[r][c][cls]++;
          n_obs[r][c]++;
        }
      }
    }
  }

  const obs_probs = Array.from({ length: GRID_SIZE }, (_, r) =>
    Array.from({ length: GRID_SIZE }, (_, c) => {
      const total = n_obs[r][c];
      if (total === 0) return new Array(N_CLASSES).fill(0);
      return obs_counts[r][c].map(v => v / total);
    })
  );

  return { observed_counts: obs_counts, observed_probs: obs_probs, n_observations: n_obs };
}

async function main() {
  const { readFileSync, writeFileSync, mkdirSync, existsSync } = await import('fs');
  const { join } = await import('path');

  const rounds: any[] = await api('/my-rounds');
  console.log(`Found ${rounds.length} rounds`);

  const outputDir = './round_data';
  const v2Dir = '../../elias/logs/offline';
  mkdirSync(outputDir, { recursive: true });

  // Index v2_R files by round_id for observation reconstruction
  const v2ByRoundId: Record<string, any> = {};
  const { readdirSync } = await import('fs');
  if (existsSync(v2Dir)) {
    for (const fname of readdirSync(v2Dir)) {
      if (!fname.startsWith('v2_R') || !fname.endsWith('.json')) continue;
      try {
        const v2data = JSON.parse(readFileSync(join(v2Dir, fname), 'utf-8'));
        if (v2data.round_id) v2ByRoundId[v2data.round_id] = v2data;
      } catch {}
    }
    console.log(`Indexed ${Object.keys(v2ByRoundId).length} v2_R files for observation data`);
  }

  for (const round of rounds) {
    const roundId = round.id;
    const roundNumber = round.round_number;
    const seedsCount = round.seeds_count ?? 5;
    const filename = `${outputDir}/round_${String(roundNumber).padStart(2, '0')}.json`;

    // Load existing file to preserve extra fields
    let existing: any = null;
    if (existsSync(filename)) {
      try {
        existing = JSON.parse(readFileSync(filename, 'utf-8'));
      } catch {}
    }

    // Load v2_R data for observation reconstruction
    const v2data = v2ByRoundId[roundId] ?? null;

    console.log(`Fetching round ${roundNumber} (${roundId})...`);

    const [predictionsRes, queriesRes, ...analysisResults] = await Promise.allSettled([
      api(`/my-predictions/${roundId}`),
      api(`/my-queries/${roundId}`),
      ...Array.from({ length: seedsCount }, (_, i) => api(`/analysis/${roundId}/${i}`)),
    ]);

    const predictions = predictionsRes.status === 'fulfilled' ? predictionsRes.value : null;
    const queries = queriesRes.status === 'fulfilled' ? queriesRes.value : null;
    const analyses = analysisResults.map(r => r.status === 'fulfilled' ? r.value : null);

    const existingSeeds = existing?.seeds ?? [];

    const seeds = analyses.map((a, i) => {
      const existingSeed = existingSeeds.find((s: any) => s.seed_index === i) ?? {};
      const newSeed: any = {
        seed_index: i,
        prediction: a?.prediction,
        ground_truth: a?.ground_truth,
        score: a?.score,
        argmax_grid: predictions?.[i]?.argmax_grid ?? null,
        confidence_grid: predictions?.[i]?.confidence_grid ?? null,
      };

      // Preserve any existing fields not yet in newSeed
      // (keeps observation data from previous fetches/scripts)
      for (const key of Object.keys(existingSeed)) {
        if (!(key in newSeed)) {
          newSeed[key] = existingSeed[key];
        }
      }

      // If still no observations, try reconstructing from v2_R query grids
      if (!('observed_probs' in newSeed)) {
        const v2seed = v2data?.seeds?.[String(i)];
        const v2queries = v2seed?.queries ?? [];
        if (v2queries.length > 0 && v2queries[0]?.grid) {
          const obs = reconstructObservations(v2queries);
          newSeed.observed_counts = obs.observed_counts;
          newSeed.observed_probs = obs.observed_probs;
          newSeed.n_observations = obs.n_observations;
        }
      }

      return newSeed;
    });

    const output = {
      round_id: roundId,
      round_number: roundNumber,
      status: round.status,
      map_width: round.map_width,
      map_height: round.map_height,
      seeds_count: seedsCount,
      round_weight: round.round_weight,
      round_score: round.round_score,
      seed_scores: round.seed_scores,
      rank: round.rank,
      queries_used: round.queries_used,
      queries_max: round.queries_max,
      initial_grid: round.initial_grid,
      queries: queries,
      seeds: seeds,
    };

    writeFileSync(filename, JSON.stringify(output));
    console.log(`  -> ${filename} (v2 obs: ${v2data ? 'yes' : 'no'})`);
  }

  console.log('Done!');
}

main().catch(console.error);
