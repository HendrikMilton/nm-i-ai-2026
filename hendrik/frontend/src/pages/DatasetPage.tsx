import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ChevronLeft, ChevronRight, Eye, EyeOff, Tag, Crosshair } from 'lucide-react';
import { Breadcrumbs } from '../components/Breadcrumbs';

const API = 'http://localhost:3003';

interface CocoImage {
    id: number;
    file_name: string;
    width: number;
    height: number;
}

interface CocoCategory {
    id: number;
    name: string;
    supercategory: string;
}

interface CocoAnnotation {
    id: number;
    image_id: number;
    category_id: number;
    bbox: [number, number, number, number]; // x, y, w, h
    area: number;
    iscrowd: number;
    product_code?: string;
    product_name?: string;
    corrected?: boolean;
}

interface Prediction {
    image_id: number;
    category_id: number;
    bbox: [number, number, number, number];
    score: number;
}

interface CocoDataset {
    images: CocoImage[];
    categories: CocoCategory[];
    annotations: CocoAnnotation[];
}

// Generate a stable color per category
const categoryColor = (id: number): string => {
    const hue = (id * 137.508) % 360; // golden angle
    return `hsl(${hue}, 70%, 55%)`;
};

type OverlayMode = 'gt' | 'predictions' | 'both';

// Compute IoU between two COCO-format bboxes [x, y, w, h]
function computeIoU(a: number[], b: number[]): number {
    const ax1 = a[0], ay1 = a[1], ax2 = a[0] + a[2], ay2 = a[1] + a[3];
    const bx1 = b[0], by1 = b[1], bx2 = b[0] + b[2], by2 = b[1] + b[3];
    const ix1 = Math.max(ax1, bx1), iy1 = Math.max(ay1, by1);
    const ix2 = Math.min(ax2, bx2), iy2 = Math.min(ay2, by2);
    const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
    const union = a[2] * a[3] + b[2] * b[3] - inter;
    return union > 0 ? inter / union : 0;
}

// Find best matching GT box for a prediction
function bestIoU(pred: { bbox: number[] }, gts: { bbox: number[] }[]): number {
    let best = 0;
    for (const gt of gts) {
        const iou = computeIoU(pred.bbox, gt.bbox);
        if (iou > best) best = iou;
    }
    return best;
}

export function DatasetPage() {
    const [dataset, setDataset] = useState<CocoDataset | null>(null);
    const [loading, setLoading] = useState(true);
    const [currentIdx, setCurrentIdx] = useState(0);
    const [showBoxes, setShowBoxes] = useState(true);
    const [showLabels, setShowLabels] = useState(true);
    const [hoveredAnn, setHoveredAnn] = useState<number | null>(null);
    const [selectedAnn, setSelectedAnn] = useState<CocoAnnotation | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const containerRef = useRef<HTMLDivElement>(null);

    // Prediction overlay state
    const [availableRuns, setAvailableRuns] = useState<string[]>([]);
    const [selectedRun, setSelectedRun] = useState<string>('');
    const [predictions, setPredictions] = useState<Prediction[]>([]);
    const [overlayMode, setOverlayMode] = useState<OverlayMode>('gt');
    const [minConfidence, setMinConfidence] = useState(0.25);

    useEffect(() => {
        fetch(`${API}/dataset/annotations`)
            .then((r) => r.json())
            .then((data: CocoDataset) => {
                data.images.sort((a, b) => a.id - b.id);
                setDataset(data);
            })
            .catch((err) => console.error('Failed to load annotations:', err))
            .finally(() => setLoading(false));

        fetch(`${API}/predictions/list`)
            .then((r) => r.json())
            .then((data) => {
                setAvailableRuns(data.runs || []);
                if (data.runs?.length > 0) setSelectedRun(data.runs[data.runs.length - 1]);
            })
            .catch(() => {});
    }, []);

    // Load predictions when run changes
    useEffect(() => {
        if (!selectedRun) { setPredictions([]); return; }
        fetch(`${API}/predictions/${selectedRun}`)
            .then((r) => r.json())
            .then((data) => setPredictions(data))
            .catch(() => setPredictions([]));
    }, [selectedRun]);

    const categoryMap = useMemo(() => {
        if (!dataset) return new Map<number, CocoCategory>();
        return new Map(dataset.categories.map((c) => [c.id, c]));
    }, [dataset]);

    const annotationsByImage = useMemo(() => {
        if (!dataset) return new Map<number, CocoAnnotation[]>();
        const map = new Map<number, CocoAnnotation[]>();
        for (const ann of dataset.annotations) {
            const list = map.get(ann.image_id) || [];
            list.push(ann);
            map.set(ann.image_id, list);
        }
        return map;
    }, [dataset]);

    const predictionsByImage = useMemo(() => {
        const map = new Map<number, Prediction[]>();
        for (const pred of predictions) {
            const list = map.get(pred.image_id) || [];
            list.push(pred);
            map.set(pred.image_id, list);
        }
        return map;
    }, [predictions]);

    const currentImage = dataset?.images[currentIdx] ?? null;
    const currentAnnotations = currentImage
        ? annotationsByImage.get(currentImage.id) || []
        : [];
    const currentPredictions = currentImage
        ? (predictionsByImage.get(currentImage.id) || []).filter((p) => p.score >= minConfidence)
        : [];

    // Category stats for current image
    const categoryStats = useMemo(() => {
        const counts = new Map<number, number>();
        const source = overlayMode === 'predictions' ? currentPredictions.map((p) => ({ category_id: p.category_id })) : currentAnnotations;
        for (const ann of source) {
            counts.set(ann.category_id, (counts.get(ann.category_id) || 0) + 1);
        }
        return Array.from(counts.entries())
            .map(([catId, count]) => ({
                id: catId,
                name: categoryMap.get(catId)?.name ?? `Unknown (${catId})`,
                count,
            }))
            .sort((a, b) => b.count - a.count);
    }, [currentAnnotations, currentPredictions, overlayMode, categoryMap]);

    // Filtered images by search
    const filteredImages = useMemo(() => {
        if (!dataset || !searchQuery.trim()) return dataset?.images ?? [];
        const q = searchQuery.toLowerCase();
        const matchingCatIds = new Set(
            dataset.categories.filter((c) => c.name.toLowerCase().includes(q)).map((c) => c.id)
        );
        if (matchingCatIds.size === 0) return dataset.images;
        return dataset.images.filter((img) => {
            const anns = annotationsByImage.get(img.id) || [];
            return anns.some((a) => matchingCatIds.has(a.category_id));
        });
    }, [dataset, searchQuery, annotationsByImage]);

    const navigate = useCallback(
        (delta: number) => {
            if (!dataset) return;
            const total = filteredImages.length;
            const newFilterIdx = ((currentIdx + delta) % total + total) % total;
            const targetImage = filteredImages[newFilterIdx];
            const realIdx = dataset.images.findIndex((img) => img.id === targetImage.id);
            setCurrentIdx(realIdx >= 0 ? realIdx : 0);
            setSelectedAnn(null);
        },
        [dataset, currentIdx, filteredImages]
    );

    // Keyboard navigation
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
            if (e.key === 'ArrowLeft' || e.key === 'a') navigate(-1);
            if (e.key === 'ArrowRight' || e.key === 'd') navigate(1);
            if (e.key === 'b') setShowBoxes((p) => !p);
            if (e.key === 'l') setShowLabels((p) => !p);
            if (e.key === 'p') setOverlayMode((m) => m === 'gt' ? 'predictions' : m === 'predictions' ? 'both' : 'gt');
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [navigate]);

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
            </div>
        );
    }

    if (!dataset || !currentImage) {
        return <div className="text-error text-center py-20">Failed to load dataset</div>;
    }

    const filterIdx = filteredImages.findIndex((img) => img.id === currentImage.id);

    const showGT = overlayMode === 'gt' || overlayMode === 'both';
    const showPreds = overlayMode === 'predictions' || overlayMode === 'both';

    return (
        <div className="flex flex-col gap-4">
            <Breadcrumbs crumbs={[
                { label: '2 - NorgesGruppen Data', to: '/challenges/2' },
                { label: 'Dataset' },
            ]} />
            {/* Top bar */}
            <div className="flex items-center gap-4 flex-wrap">
                <h1 className="text-xl font-semibold text-foreground">Dataset Explorer</h1>
                <div className="flex-1" />
                <input
                    type="text"
                    placeholder="Search products..."
                    value={searchQuery}
                    onChange={(e) => {
                        setSearchQuery(e.target.value);
                        setCurrentIdx(0);
                    }}
                    className="px-3 py-1.5 text-sm bg-surface border border-border rounded-lg text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/30 w-64"
                />
            </div>

            {/* Navigation + controls */}
            <div className="flex items-center gap-3 bg-surface rounded-lg border border-border/60 px-4 py-2.5 shadow-gcp flex-wrap">
                <button onClick={() => navigate(-1)} className="p-1.5 rounded hover:bg-surface-dim text-secondary hover:text-foreground transition-colors">
                    <ChevronLeft className="w-5 h-5" />
                </button>
                <span className="text-sm font-mono text-foreground min-w-[120px] text-center">
                    {filterIdx + 1} / {filteredImages.length}
                </span>
                <button onClick={() => navigate(1)} className="p-1.5 rounded hover:bg-surface-dim text-secondary hover:text-foreground transition-colors">
                    <ChevronRight className="w-5 h-5" />
                </button>

                <div className="h-5 w-px bg-border/60 mx-2" />

                <span className="text-xs font-mono text-secondary">{currentImage.file_name}</span>
                <span className="text-xs text-muted">
                    {currentImage.width}x{currentImage.height}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">
                    {currentAnnotations.length} GT
                </span>
                {selectedRun && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-warning/10 text-warning font-medium">
                        {currentPredictions.length} preds
                    </span>
                )}

                <div className="flex-1" />

                <button
                    onClick={() => setShowBoxes((p) => !p)}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                        showBoxes ? 'bg-primary/10 text-primary' : 'text-secondary hover:text-foreground'
                    }`}
                >
                    {showBoxes ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                    Boxes [B]
                </button>
                <button
                    onClick={() => setShowLabels((p) => !p)}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                        showLabels ? 'bg-primary/10 text-primary' : 'text-secondary hover:text-foreground'
                    }`}
                >
                    <Tag className="w-3.5 h-3.5" />
                    Labels [L]
                </button>
            </div>

            {/* Prediction controls */}
            {availableRuns.length > 0 && (
                <div className="flex items-center gap-3 bg-surface rounded-lg border border-border/60 px-4 py-2.5 shadow-gcp">
                    <Crosshair className="w-4 h-4 text-secondary" />
                    <span className="text-xs font-medium text-secondary">Overlay:</span>

                    {/* Mode toggle */}
                    <div className="flex rounded-lg border border-border/60 overflow-hidden">
                        {(['gt', 'predictions', 'both'] as OverlayMode[]).map((mode) => (
                            <button
                                key={mode}
                                onClick={() => setOverlayMode(mode)}
                                className={`px-3 py-1 text-xs font-medium transition-colors ${
                                    overlayMode === mode
                                        ? mode === 'gt' ? 'bg-success/15 text-success' : mode === 'predictions' ? 'bg-warning/15 text-warning' : 'bg-primary/10 text-primary'
                                        : 'text-secondary hover:bg-surface-dim'
                                }`}
                            >
                                {mode === 'gt' ? 'Ground Truth' : mode === 'predictions' ? 'Predictions' : 'Both'}
                            </button>
                        ))}
                    </div>

                    <span className="text-xs text-muted">[P]</span>

                    <div className="h-5 w-px bg-border/60 mx-1" />

                    {/* Run selector */}
                    <span className="text-xs text-secondary">Run:</span>
                    <select
                        value={selectedRun}
                        onChange={(e) => setSelectedRun(e.target.value)}
                        className="px-2 py-1 text-xs bg-surface border border-border rounded text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    >
                        {availableRuns.map((run) => (
                            <option key={run} value={run}>{run}</option>
                        ))}
                    </select>

                    <div className="h-5 w-px bg-border/60 mx-1" />

                    {/* Confidence threshold */}
                    <span className="text-xs text-secondary">Min conf:</span>
                    <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={minConfidence}
                        onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
                        className="w-20 accent-primary"
                    />
                    <span className="text-xs font-mono text-foreground w-8">{minConfidence.toFixed(2)}</span>
                </div>
            )}

            {/* Main content: image + sidebar */}
            <div className="flex gap-4" style={{ height: 'calc(100vh - 280px)' }}>
                {/* Image viewer */}
                <div
                    ref={containerRef}
                    className="flex-1 bg-surface rounded-lg border border-border/60 shadow-gcp overflow-hidden relative flex items-center justify-center"
                >
                    <div className="relative inline-block" style={{ maxHeight: '100%', maxWidth: '100%' }}>
                        <img
                            src={`${API}/dataset/images/${currentImage.file_name}`}
                            alt={currentImage.file_name}
                            className="block max-h-full max-w-full object-contain"
                            style={{ maxHeight: 'calc(100vh - 300px)' }}
                            draggable={false}
                        />
                        {showBoxes && (
                            <svg
                                className="absolute inset-0 w-full h-full pointer-events-none"
                                viewBox={`0 0 ${currentImage.width} ${currentImage.height}`}
                                preserveAspectRatio="xMidYMid meet"
                            >
                                {/* Ground truth boxes (green-ish) */}
                                {showGT && currentAnnotations.map((ann) => {
                                    const [x, y, w, h] = ann.bbox;
                                    const color = overlayMode === 'both' ? 'hsl(140, 70%, 45%)' : categoryColor(ann.category_id);
                                    const isHovered = hoveredAnn === ann.id;
                                    const isSelected = selectedAnn?.id === ann.id;
                                    const highlight = isHovered || isSelected;

                                    return (
                                        <g key={`gt-${ann.id}`} style={{ pointerEvents: 'all' }}>
                                            <rect
                                                x={x} y={y} width={w} height={h}
                                                fill={highlight ? `${color}33` : 'transparent'}
                                                stroke={color}
                                                strokeWidth={highlight ? 4 : 2}
                                                rx={2}
                                                className="cursor-pointer"
                                                onMouseEnter={() => setHoveredAnn(ann.id)}
                                                onMouseLeave={() => setHoveredAnn(null)}
                                                onClick={() => setSelectedAnn(ann)}
                                            />
                                            {showLabels && overlayMode !== 'both' && (
                                                <g>
                                                    <rect
                                                        x={x} y={Math.max(0, y - 28)}
                                                        width={Math.min(w, 200)} height={26}
                                                        fill={color} rx={2}
                                                        opacity={highlight ? 1 : 0.8}
                                                    />
                                                    <text
                                                        x={x + 4} y={Math.max(0, y - 28) + 19}
                                                        fill="white" fontSize="18" fontFamily="monospace" fontWeight="bold"
                                                    >
                                                        {(categoryMap.get(ann.category_id)?.name ?? `#${ann.category_id}`).slice(0, 28)}
                                                    </text>
                                                </g>
                                            )}
                                        </g>
                                    );
                                })}
                                {/* Prediction boxes (orange-ish / dashed in both mode) */}
                                {showPreds && currentPredictions.map((pred, i) => {
                                    const [x, y, w, h] = pred.bbox;
                                    const iou = bestIoU(pred, currentAnnotations);
                                    const iouColor = iou >= 0.5 ? '#22c55e' : '#ef4444';
                                    const color = overlayMode === 'both' ? 'hsl(35, 90%, 55%)' : categoryColor(pred.category_id);

                                    return (
                                        <g key={`pred-${i}`} style={{ pointerEvents: 'all' }}>
                                            <rect
                                                x={x} y={y} width={w} height={h}
                                                fill="transparent"
                                                stroke={color}
                                                strokeWidth={2}
                                                strokeDasharray={overlayMode === 'both' ? '6 3' : 'none'}
                                                rx={2}
                                            />
                                            {showLabels && (
                                                <g>
                                                    <rect
                                                        x={x}
                                                        y={Math.max(0, y - 24)}
                                                        width={100} height={20}
                                                        fill="rgba(0,0,0,0.7)" rx={2}
                                                    />
                                                    <text
                                                        x={x + 4}
                                                        y={Math.max(0, y - 24) + 15}
                                                        fontSize="14" fontFamily="monospace" fontWeight="bold"
                                                    >
                                                        <tspan fill="white">{pred.score.toFixed(2)}/</tspan>
                                                        <tspan fill={iouColor}>{iou.toFixed(2)}</tspan>
                                                    </text>
                                                </g>
                                            )}
                                        </g>
                                    );
                                })}
                            </svg>
                        )}
                    </div>
                </div>

                {/* Right sidebar: annotations list + selected detail */}
                <div className="w-80 flex flex-col gap-3 flex-shrink-0">
                    {/* Selected annotation detail */}
                    {selectedAnn && (
                        <div className="bg-surface rounded-lg border border-border/60 shadow-gcp p-4">
                            <div className="flex items-center justify-between mb-3">
                                <span className="text-sm font-semibold text-foreground">Selected</span>
                                <button
                                    onClick={() => setSelectedAnn(null)}
                                    className="text-xs text-secondary hover:text-foreground"
                                >
                                    Close
                                </button>
                            </div>
                            <div className="space-y-2 text-xs">
                                <div>
                                    <span className="text-muted">Category: </span>
                                    <span className="text-foreground font-medium">
                                        {categoryMap.get(selectedAnn.category_id)?.name}
                                    </span>
                                </div>
                                <div>
                                    <span className="text-muted">ID: </span>
                                    <span className="font-mono text-foreground">{selectedAnn.category_id}</span>
                                </div>
                                <div>
                                    <span className="text-muted">BBox: </span>
                                    <span className="font-mono text-foreground">
                                        [{selectedAnn.bbox.map((v) => Math.round(v)).join(', ')}]
                                    </span>
                                </div>
                                <div>
                                    <span className="text-muted">Area: </span>
                                    <span className="font-mono text-foreground">{selectedAnn.area.toLocaleString()}px</span>
                                </div>
                                {selectedAnn.product_code && (
                                    <div>
                                        <span className="text-muted">Barcode: </span>
                                        <span className="font-mono text-foreground">{selectedAnn.product_code}</span>
                                    </div>
                                )}
                                {selectedAnn.product_code && (
                                    <img
                                        src={`${API}/dataset/products/${selectedAnn.product_code}/main.jpg`}
                                        alt="Product"
                                        className="w-full rounded border border-border/60 mt-2"
                                        onError={(e) => {
                                            (e.target as HTMLImageElement).style.display = 'none';
                                        }}
                                    />
                                )}
                            </div>
                        </div>
                    )}

                    {/* Category summary */}
                    <div className="bg-surface rounded-lg border border-border/60 shadow-gcp flex-1 overflow-hidden flex flex-col">
                        <div className="px-4 py-3 border-b border-border/60">
                            <span className="text-sm font-semibold text-foreground">
                                Categories ({categoryStats.length})
                            </span>
                        </div>
                        <div className="flex-1 overflow-y-auto">
                            {categoryStats.map((stat) => (
                                <div
                                    key={stat.id}
                                    className="flex items-center gap-2 px-4 py-1.5 hover:bg-surface-dim cursor-default text-xs border-b border-border/20"
                                >
                                    <div
                                        className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                                        style={{ backgroundColor: categoryColor(stat.id) }}
                                    />
                                    <span className="text-foreground truncate flex-1" title={stat.name}>
                                        {stat.name}
                                    </span>
                                    <span className="text-muted font-mono">{stat.count}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            {/* Keyboard shortcuts hint */}
            <div className="text-xs text-muted text-center">
                Arrow keys or A/D to navigate | B toggle boxes | L toggle labels | P cycle overlay mode | Click box for details
            </div>
        </div>
    );
}
