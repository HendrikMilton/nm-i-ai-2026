import { useMemo } from 'react';

export interface Viewport {
    x: number;
    y: number;
    w: number;
    h: number;
}

export const TERRAIN_COLORS: Record<number, string> = {
    0: '#C8B88A',   // Empty
    10: '#1F3A5F',  // Ocean
    11: '#C9B88B',  // Plains
    1: '#D4760A',   // Settlement
    2: '#0D7490',   // Port
    3: '#7F1E1D',   // Ruin
    4: '#2D5A27',   // Forest
    5: '#6C7280',   // Mountain
};

export const TERRAIN_LABELS: Record<number, string> = {
    10: 'Ocean', 11: 'Plains', 0: 'Empty', 1: 'Settlement',
    2: 'Port', 3: 'Ruin', 4: 'Forest', 5: 'Mountain',
};

const CLASS_COLORS = ['#C8B88A', '#D4760A', '#0D7490', '#7F1E1D', '#2D5A27', '#6C7280'];
const CLASS_LABELS = ['Empty', 'Settlement', 'Port', 'Ruin', 'Forest', 'Mountain'];

interface TerrainGridProps {
    grid: number[][];
    cellSize?: number;
    title?: string;
    viewports?: Viewport[];
    selectedViewport?: number | null;
    onViewportClick?: (i: number) => void;
}

export function TerrainGrid({
    grid, cellSize = 12, title, viewports, selectedViewport, onViewportClick,
}: TerrainGridProps) {
    const h = grid.length;
    const w = grid[0]?.length ?? 0;
    const svgW = w * cellSize;
    const svgH = h * cellSize;

    const cells = useMemo(() => {
        const result = [];
        for (let r = 0; r < h; r++) {
            for (let c = 0; c < w; c++) {
                const val = grid[r][c];
                result.push(
                    <rect key={`${r}-${c}`} x={c * cellSize} y={r * cellSize}
                        width={cellSize} height={cellSize}
                        fill={TERRAIN_COLORS[val] ?? '#111'} />
                );
            }
        }
        return result;
    }, [grid, cellSize, h, w]);

    const vpOverlays = useMemo(() => {
        if (!viewports) return null;
        return viewports.map((vp, i) => (
            <rect key={`vp-${i}`}
                x={vp.x * cellSize} y={vp.y * cellSize}
                width={vp.w * cellSize} height={vp.h * cellSize}
                fill="none"
                stroke={selectedViewport === i ? '#facc15' : '#fb923c'}
                strokeWidth={selectedViewport === i ? 2 : 1}
                strokeOpacity={selectedViewport === i ? 1 : 0.5}
                style={{ cursor: onViewportClick ? 'pointer' : 'default' }}
                onClick={() => onViewportClick?.(i)}
            />
        ));
    }, [viewports, cellSize, selectedViewport, onViewportClick]);

    return (
        <div>
            {title && <div className="text-xs font-medium text-secondary mb-1">{title}</div>}
            <svg width={svgW} height={svgH} className="border border-border/40 rounded">
                {cells}
                {vpOverlays}
            </svg>
        </div>
    );
}

interface HeatmapGridProps {
    values: number[][];
    cellSize?: number;
    title?: string;
    maxVal?: number;
}

export function HeatmapGrid({ values, cellSize = 12, title, maxVal }: HeatmapGridProps) {
    const h = values.length;
    const w = values[0]?.length ?? 0;
    const mx = maxVal ?? Math.max(1, ...values.flat());

    const cells = useMemo(() => {
        const result = [];
        for (let r = 0; r < h; r++) {
            for (let c = 0; c < w; c++) {
                const v = values[r][c];
                const t = Math.min(1, v / mx);
                const r_ = Math.round(10 + t * 30);
                const g_ = Math.round(10 + t * 80);
                const b_ = Math.round(30 + t * 225);
                result.push(
                    <rect key={`${r}-${c}`} x={c * cellSize} y={r * cellSize}
                        width={cellSize} height={cellSize}
                        fill={v === 0 ? '#111' : `rgb(${r_},${g_},${b_})`} />
                );
            }
        }
        return result;
    }, [values, cellSize, h, w, mx]);

    return (
        <div>
            {title && <div className="text-xs font-medium text-secondary mb-1">{title}</div>}
            <svg width={w * cellSize} height={h * cellSize} className="border border-border/40 rounded">
                {cells}
            </svg>
        </div>
    );
}

interface ProbGridProps {
    probs: number[][][];  // HxWx6
    cellSize?: number;
    title?: string;
}

export function ProbGrid({ probs, cellSize = 12, title }: ProbGridProps) {
    const h = probs.length;
    const w = probs[0]?.length ?? 0;

    const cells = useMemo(() => {
        const result = [];
        for (let r = 0; r < h; r++) {
            for (let c = 0; c < w; c++) {
                const p = probs[r][c];
                if (!p || p.every(v => v === 0)) {
                    result.push(
                        <rect key={`${r}-${c}`} x={c * cellSize} y={r * cellSize}
                            width={cellSize} height={cellSize} fill="#111" />
                    );
                    continue;
                }
                const maxIdx = p.indexOf(Math.max(...p));
                const conf = p[maxIdx];
                result.push(
                    <rect key={`${r}-${c}`} x={c * cellSize} y={r * cellSize}
                        width={cellSize} height={cellSize}
                        fill={CLASS_COLORS[maxIdx]}
                        opacity={0.3 + 0.7 * conf} />
                );
            }
        }
        return result;
    }, [probs, cellSize, h, w]);

    return (
        <div>
            {title && <div className="text-xs font-medium text-secondary mb-1">{title}</div>}
            <svg width={w * cellSize} height={h * cellSize} className="border border-border/40 rounded">
                {cells}
            </svg>
        </div>
    );
}

export function TerrainLegend() {
    return (
        <div className="flex flex-wrap gap-3 text-xs text-secondary">
            {Object.entries(TERRAIN_LABELS).map(([code, label]) => (
                <div key={code} className="flex items-center gap-1.5">
                    <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: TERRAIN_COLORS[Number(code)] }} />
                    {label}
                </div>
            ))}
        </div>
    );
}

export function ClassLegend() {
    return (
        <div className="flex flex-wrap gap-3 text-xs text-secondary">
            {CLASS_LABELS.map((label, i) => (
                <div key={i} className="flex items-center gap-1.5">
                    <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: CLASS_COLORS[i] }} />
                    {label}
                </div>
            ))}
        </div>
    );
}
