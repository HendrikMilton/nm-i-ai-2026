const COOKIE = 'access_token=REDACTED_TOKEN';
const BASE = 'https://api.ainm.no/astar-island';
const HEADERS = {
  'accept': '*/*',
  'origin': 'https://app.ainm.no',
  'referer': 'https://app.ainm.no/',
  'cookie': COOKIE,
};

async function api(path: string) {
  const res = await fetch(`${BASE}${path}`, { headers: HEADERS });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json();
}

async function main() {
  const rounds: any[] = await api('/my-rounds');
  console.log(`Found ${rounds.length} rounds`);

  const outputDir = './round_data';
  const { mkdirSync } = await import('fs');
  mkdirSync(outputDir, { recursive: true });

  for (const round of rounds) {
    const roundId = round.id;
    const roundNumber = round.round_number;
    const seedsCount = round.seeds_count ?? 5;
    console.log(`Fetching round ${roundNumber} (${roundId}), ${seedsCount} seeds...`);

    // Fetch predictions (list of per-seed argmax_grids), queries, and analysis for each seed
    const [predictionsRes, queriesRes, ...analysisResults] = await Promise.allSettled([
      api(`/my-predictions/${roundId}`),
      api(`/my-queries/${roundId}`),
      ...Array.from({ length: seedsCount }, (_, i) => api(`/analysis/${roundId}/${i}`)),
    ]);

    const predictions = predictionsRes.status === 'fulfilled' ? predictionsRes.value : null;
    const queries = queriesRes.status === 'fulfilled' ? queriesRes.value : null;
    const analyses = analysisResults.map(r => r.status === 'fulfilled' ? r.value : null);

    // Build per-seed data from analysis endpoints
    const seeds = analyses.map((a, i) => ({
      seed_index: i,
      prediction: a?.prediction,
      ground_truth: a?.ground_truth,
      score: a?.score,
      // argmax_grid from predictions endpoint (per-seed)
      argmax_grid: predictions?.[i]?.argmax_grid ?? null,
      confidence_grid: predictions?.[i]?.confidence_grid ?? null,
    }));

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

    const filename = `${outputDir}/round_${String(roundNumber).padStart(2, '0')}.json`;
    await Bun.write(filename, JSON.stringify(output, null, 2));
    console.log(`  -> ${filename}`);
  }

  console.log('Done!');
}

main().catch(console.error);
