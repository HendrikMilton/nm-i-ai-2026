import { useState, useEffect, useCallback } from 'react';
import { TerrainGrid, HeatmapGrid, ProbGrid, TerrainLegend, ClassLegend, type Viewport } from '../components/TerrainGrid';

interface QueryGrid {
    viewport: Viewport;
    grid: number[][];
}

interface SeedData {
    initial_grid: number[][];
    query_grids: QueryGrid[];
    observed_probs: number[][][];
    n_observations: number[][];
}

interface SubmitData {
    round_id: string;
    round_number: number;
    timestamp: string;
    seeds: Record<string, SeedData>;
}

export function AstarPage() {
    const [availableRounds, setAvailableRounds] = useState<number[]>([]);
    const [roundNumber, setRoundNumber] = useState<number | null>(null);
    const [data, setData] = useState<SubmitData | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [selectedSeed, setSelectedSeed] = useState(0);
    const [selectedQuery, setSelectedQuery] = useState<number | null>(null);

    useEffect(() => {
        fetch('/api/challenge3/rounds').then(r => r.json()).then((rounds: number[]) => {
            setAvailableRounds(rounds);
            if (rounds.length > 0 && roundNumber === null) {
                setRoundNumber(rounds[rounds.length - 1]);
            }
        }).catch(() => {});
    }, []);

    const loadRound = useCallback(async (rn: number) => {
        setLoading(true);
        setError(null);
        try {
            const resp = await fetch(`/api/challenge3/round/${rn}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const json = await resp.json();
            setData(json);
            setSelectedSeed(0);
            setSelectedQuery(null);
        } catch (e: any) {
            setError(e.message);
            setData(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (roundNumber !== null) loadRound(roundNumber);
    }, [roundNumber, loadRound]);

    const seed = data?.seeds?.[String(selectedSeed)];
    const queryGrids = seed?.query_grids ?? [];
    const viewports = queryGrids.map(q => q.viewport);
    const selectedQueryData = selectedQuery !== null ? queryGrids[selectedQuery] : null;

    return (
        <div>
            <div className="flex items-center gap-4 mb-6">
                <h1 className="text-xl font-semibold text-foreground">Astar Island</h1>
                <select
                    className="px-3 py-1.5 text-sm bg-surface border border-border rounded-md text-foreground"
                    value={roundNumber}
                    onChange={e => setRoundNumber(Number(e.target.value))}
                >
                    {availableRounds.map(r => (
                        <option key={r} value={r}>Round {r}</option>
                    ))}
                </select>
                {data && (
                    <span className="text-xs text-secondary">
                        Submitted {data.timestamp}
                    </span>
                )}
            </div>

            {loading && <div className="text-secondary">Loading...</div>}
            {error && <div className="text-error">Error: {error}</div>}

            {data && seed && (
                <>
                    {/* Seed tabs */}
                    <div className="flex gap-1 mb-4">
                        {[0, 1, 2, 3, 4].map(s => (
                            <button key={s}
                                onClick={() => { setSelectedSeed(s); setSelectedQuery(null); }}
                                className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
                                    selectedSeed === s
                                        ? 'bg-primary text-white'
                                        : 'bg-surface border border-border text-secondary hover:text-foreground'
                                }`}
                            >
                                Seed {s}
                                <span className="ml-1.5 text-xs opacity-60">({queryGrids.length}q)</span>
                            </button>
                        ))}
                    </div>

                    {/* Grid panel */}
                    <div className="flex gap-6 mb-6 flex-wrap">
                        <TerrainGrid
                            grid={seed.initial_grid}
                            title="Initial Grid + Query Viewports"
                            viewports={viewports}
                            selectedViewport={selectedQuery}
                            onViewportClick={i => setSelectedQuery(selectedQuery === i ? null : i)}
                        />
                        <HeatmapGrid
                            values={seed.n_observations}
                            title="Observation Coverage"
                            maxVal={8}
                        />
                        <ProbGrid
                            probs={seed.observed_probs}
                            title="Observed Probabilities (argmax)"
                        />
                    </div>

                    {/* Legend */}
                    <div className="flex gap-8 mb-6">
                        <div>
                            <div className="text-xs font-medium text-secondary mb-1">Terrain</div>
                            <TerrainLegend />
                        </div>
                        <div>
                            <div className="text-xs font-medium text-secondary mb-1">Prediction Classes</div>
                            <ClassLegend />
                        </div>
                    </div>

                    {/* Query inspector */}
                    <div className="mb-2 text-sm font-medium text-foreground">
                        Query Responses ({queryGrids.length} queries)
                    </div>
                    <div className="flex gap-2 flex-wrap mb-4">
                        {queryGrids.map((q, i) => (
                            <button key={i}
                                onClick={() => setSelectedQuery(selectedQuery === i ? null : i)}
                                className={`p-1 rounded border transition-all ${
                                    selectedQuery === i
                                        ? 'border-yellow-400 ring-2 ring-yellow-400/30'
                                        : 'border-border/40 hover:border-orange-400/50'
                                }`}
                                title={`Query ${i}: viewport (${q.viewport.x},${q.viewport.y}) ${q.viewport.w}x${q.viewport.h}`}
                            >
                                <TerrainGrid grid={q.grid} cellSize={4} />
                            </button>
                        ))}
                    </div>

                    {/* Selected query detail */}
                    {selectedQueryData && (
                        <div className="bg-surface border border-border rounded-lg p-4">
                            <div className="flex items-center gap-4 mb-3">
                                <span className="text-sm font-medium text-foreground">
                                    Query {selectedQuery}
                                </span>
                                <span className="text-xs text-secondary">
                                    Viewport: ({selectedQueryData.viewport.x}, {selectedQueryData.viewport.y})
                                    {' '}{selectedQueryData.viewport.w}×{selectedQueryData.viewport.h}
                                </span>
                            </div>
                            <div className="flex gap-4 items-start">
                                <TerrainGrid
                                    grid={selectedQueryData.grid}
                                    cellSize={16}
                                    title="Query Response (15×15)"
                                />
                                <QueryStats grid={selectedQueryData.grid} />
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

function QueryStats({ grid }: { grid: number[][] }) {
    const counts: Record<number, number> = {};
    let total = 0;
    for (const row of grid) {
        for (const val of row) {
            counts[val] = (counts[val] ?? 0) + 1;
            total++;
        }
    }
    const terrainLabels: Record<number, string> = {
        0: 'Empty', 1: 'Settlement', 2: 'Port', 3: 'Ruin',
        4: 'Forest', 5: 'Mountain', 10: 'Ocean', 11: 'Plains',
    };
    const sorted = Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]));

    return (
        <div className="text-xs text-secondary space-y-1">
            <div className="font-medium text-foreground mb-2">Terrain Breakdown</div>
            {sorted.map(([code, count]) => (
                <div key={code} className="flex items-center gap-2">
                    <div className="w-16 bg-border/20 rounded-full h-2 overflow-hidden">
                        <div className="h-full rounded-full" style={{
                            width: `${100 * count / total}%`,
                            backgroundColor: ({'0':'#C8B88A','1':'#D4760A','2':'#0D7490','3':'#7F1E1D','4':'#2D5A27','5':'#6C7280','10':'#1F3A5F','11':'#C9B88B'} as any)[code],
                        }} />
                    </div>
                    <span className="w-20">{terrainLabels[Number(code)] ?? code}</span>
                    <span className="tabular-nums">{count} ({(100 * count / total).toFixed(0)}%)</span>
                </div>
            ))}
        </div>
    );
}
