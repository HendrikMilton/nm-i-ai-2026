import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Eye, EyeOff, Tag } from 'lucide-react';
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

    useEffect(() => {
        fetch(`${API}/dataset/annotations`)
            .then((r) => r.json())
            .then((data: CocoDataset) => {
                data.images.sort((a, b) => a.id - b.id);
                setDataset(data);
            })
            .catch((err) => console.error('Failed to load annotations:', err))
            .finally(() => setLoading(false));
    }, []);

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

    const currentImage = dataset?.images[currentIdx] ?? null;
    const currentAnnotations = currentImage
        ? annotationsByImage.get(currentImage.id) || []
        : [];

    // Category stats for current image
    const categoryStats = useMemo(() => {
        const counts = new Map<number, number>();
        for (const ann of currentAnnotations) {
            counts.set(ann.category_id, (counts.get(ann.category_id) || 0) + 1);
        }
        return Array.from(counts.entries())
            .map(([catId, count]) => ({
                id: catId,
                name: categoryMap.get(catId)?.name ?? `Unknown (${catId})`,
                count,
            }))
            .sort((a, b) => b.count - a.count);
    }, [currentAnnotations, categoryMap]);

    // Filtered images by search
    const filteredImages = useMemo(() => {
        if (!dataset || !searchQuery.trim()) return dataset?.images ?? [];
        const q = searchQuery.toLowerCase();
        // Search by category name - find images containing that product
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
            // Map back to full dataset index
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
            if (e.target instanceof HTMLInputElement) return;
            if (e.key === 'ArrowLeft' || e.key === 'a') navigate(-1);
            if (e.key === 'ArrowRight' || e.key === 'd') navigate(1);
            if (e.key === 'b') setShowBoxes((p) => !p);
            if (e.key === 'l') setShowLabels((p) => !p);
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
            <div className="flex items-center gap-3 bg-surface rounded-lg border border-border/60 px-4 py-2.5 shadow-gcp">
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
                <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                    {currentAnnotations.length} boxes
                </span>

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

            {/* Main content: image + sidebar */}
            <div className="flex gap-4" style={{ height: 'calc(100vh - 220px)' }}>
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
                            style={{ maxHeight: 'calc(100vh - 240px)' }}
                            draggable={false}
                        />
                        {showBoxes && (
                            <svg
                                className="absolute inset-0 w-full h-full pointer-events-none"
                                viewBox={`0 0 ${currentImage.width} ${currentImage.height}`}
                                preserveAspectRatio="xMidYMid meet"
                            >
                                {currentAnnotations.map((ann) => {
                                    const [x, y, w, h] = ann.bbox;
                                    const color = categoryColor(ann.category_id);
                                    const isHovered = hoveredAnn === ann.id;
                                    const isSelected = selectedAnn?.id === ann.id;
                                    const highlight = isHovered || isSelected;

                                    return (
                                        <g key={ann.id} style={{ pointerEvents: 'all' }}>
                                            <rect
                                                x={x}
                                                y={y}
                                                width={w}
                                                height={h}
                                                fill={highlight ? `${color}33` : 'transparent'}
                                                stroke={color}
                                                strokeWidth={highlight ? 4 : 2}
                                                rx={2}
                                                className="cursor-pointer"
                                                onMouseEnter={() => setHoveredAnn(ann.id)}
                                                onMouseLeave={() => setHoveredAnn(null)}
                                                onClick={() => setSelectedAnn(ann)}
                                            />
                                            {showLabels && (
                                                <g>
                                                    <rect
                                                        x={x}
                                                        y={Math.max(0, y - 22)}
                                                        width={Math.min(w, 200)}
                                                        height={20}
                                                        fill={color}
                                                        rx={2}
                                                        opacity={highlight ? 1 : 0.8}
                                                    />
                                                    <text
                                                        x={x + 4}
                                                        y={Math.max(0, y - 22) + 14}
                                                        fill="white"
                                                        fontSize="12"
                                                        fontFamily="monospace"
                                                        fontWeight="bold"
                                                    >
                                                        {(categoryMap.get(ann.category_id)?.name ?? `#${ann.category_id}`).slice(0, 28)}
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
                Arrow keys or A/D to navigate | B toggle boxes | L toggle labels | Click box for details
            </div>
        </div>
    );
}
