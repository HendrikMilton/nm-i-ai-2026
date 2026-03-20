import { useState, useEffect, useMemo } from 'react';
import { Package, Search, ArrowUpDown, Image as ImageIcon } from 'lucide-react';
import { Breadcrumbs } from '../components/Breadcrumbs';

const API = 'http://localhost:3003';

interface Product {
    product_code: string;
    product_name: string;
    annotation_count: number;
    corrected_count: number;
    has_images: boolean;
    image_types: string[];
}

interface ProductMetadata {
    total_products: number;
    products_with_images: number;
    products_without_images: number;
    total_images: number;
    products: Product[];
}

const VIEW_ORDER = ['main', 'front', 'back', 'left', 'right', 'top', 'bottom'];

type SortKey = 'name' | 'annotations' | 'images';

export function ProductsPage() {
    const [metadata, setMetadata] = useState<ProductMetadata | null>(null);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
    const [selectedView, setSelectedView] = useState('main');
    const [sortBy, setSortBy] = useState<SortKey>('annotations');
    const [sortAsc, setSortAsc] = useState(false);

    useEffect(() => {
        fetch(`${API}/dataset/product-metadata`)
            .then((r) => r.json())
            .then((data: ProductMetadata) => setMetadata(data))
            .catch((err) => console.error('Failed to load metadata:', err))
            .finally(() => setLoading(false));
    }, []);

    const filtered = useMemo(() => {
        if (!metadata) return [];
        let products = metadata.products.filter((p) => p.has_images);
        if (search.trim()) {
            const q = search.toLowerCase();
            products = products.filter(
                (p) =>
                    p.product_name.toLowerCase().includes(q) ||
                    p.product_code.includes(q)
            );
        }
        products.sort((a, b) => {
            let cmp = 0;
            if (sortBy === 'name') cmp = a.product_name.localeCompare(b.product_name);
            else if (sortBy === 'annotations') cmp = a.annotation_count - b.annotation_count;
            else if (sortBy === 'images') cmp = a.image_types.length - b.image_types.length;
            return sortAsc ? cmp : -cmp;
        });
        return products;
    }, [metadata, search, sortBy, sortAsc]);

    const toggleSort = (key: SortKey) => {
        if (sortBy === key) setSortAsc((p) => !p);
        else {
            setSortBy(key);
            setSortAsc(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
            </div>
        );
    }

    if (!metadata) {
        return <div className="text-error text-center py-20">Failed to load product metadata</div>;
    }

    return (
        <div className="flex flex-col gap-4">
            <Breadcrumbs crumbs={[
                { label: '2 - NorgesGruppen Data', to: '/challenges/2' },
                { label: 'Products' },
            ]} />
            {/* Header */}
            <div className="flex items-center gap-4 flex-wrap">
                <h1 className="text-xl font-semibold text-foreground">Product Reference Images</h1>
                <div className="flex gap-3 text-xs text-muted">
                    <span>{metadata.total_products} products</span>
                    <span>{metadata.total_images} images</span>
                    <span>{metadata.products_without_images} missing</span>
                </div>
                <div className="flex-1" />
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
                    <input
                        type="text"
                        placeholder="Search by name or barcode..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="pl-9 pr-3 py-1.5 text-sm bg-surface border border-border rounded-lg text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/30 w-72"
                    />
                </div>
            </div>

            <div className="flex gap-4" style={{ height: 'calc(100vh - 180px)' }}>
                {/* Product list */}
                <div className="w-[480px] flex-shrink-0 bg-surface rounded-lg border border-border/60 shadow-gcp flex flex-col overflow-hidden">
                    {/* Column headers */}
                    <div className="flex items-center gap-2 px-4 py-2 border-b border-border/60 text-xs font-medium text-secondary">
                        <button
                            onClick={() => toggleSort('name')}
                            className="flex items-center gap-1 flex-1 hover:text-foreground transition-colors"
                        >
                            Product {sortBy === 'name' && <ArrowUpDown className="w-3 h-3" />}
                        </button>
                        <button
                            onClick={() => toggleSort('annotations')}
                            className="flex items-center gap-1 w-16 justify-end hover:text-foreground transition-colors"
                        >
                            Anns {sortBy === 'annotations' && <ArrowUpDown className="w-3 h-3" />}
                        </button>
                        <button
                            onClick={() => toggleSort('images')}
                            className="flex items-center gap-1 w-16 justify-end hover:text-foreground transition-colors"
                        >
                            Views {sortBy === 'images' && <ArrowUpDown className="w-3 h-3" />}
                        </button>
                    </div>

                    {/* Scrollable list */}
                    <div className="flex-1 overflow-y-auto">
                        {filtered.map((product) => (
                            <button
                                key={product.product_code}
                                onClick={() => {
                                    setSelectedProduct(product);
                                    setSelectedView(product.image_types.includes('main') ? 'main' : product.image_types[0]);
                                }}
                                className={`w-full flex items-center gap-2 px-4 py-2 text-left border-b border-border/20 transition-colors ${
                                    selectedProduct?.product_code === product.product_code
                                        ? 'bg-primary/10'
                                        : 'hover:bg-surface-dim'
                                }`}
                            >
                                <img
                                    src={`${API}/dataset/products/${product.product_code}/main.jpg`}
                                    alt=""
                                    className="w-10 h-10 object-contain rounded flex-shrink-0 bg-white"
                                    onError={(e) => {
                                        (e.target as HTMLImageElement).src = '';
                                        (e.target as HTMLImageElement).className = 'w-10 h-10 bg-surface-dim rounded flex-shrink-0';
                                    }}
                                />
                                <div className="flex-1 min-w-0">
                                    <div className="text-xs text-foreground truncate">{product.product_name}</div>
                                    <div className="text-[10px] font-mono text-muted">{product.product_code}</div>
                                </div>
                                <span className="text-xs font-mono text-secondary w-16 text-right">{product.annotation_count}</span>
                                <span className="text-xs font-mono text-muted w-16 text-right">{product.image_types.length}</span>
                            </button>
                        ))}
                        {filtered.length === 0 && (
                            <div className="text-sm text-muted text-center py-10">No products found</div>
                        )}
                    </div>

                    <div className="px-4 py-2 border-t border-border/60 text-xs text-muted">
                        {filtered.length} products
                    </div>
                </div>

                {/* Product detail */}
                <div className="flex-1 bg-surface rounded-lg border border-border/60 shadow-gcp flex flex-col overflow-hidden">
                    {selectedProduct ? (
                        <>
                            {/* Product info header */}
                            <div className="px-4 py-3 border-b border-border/60">
                                <div className="text-sm font-semibold text-foreground">{selectedProduct.product_name}</div>
                                <div className="flex gap-4 mt-1 text-xs text-muted">
                                    <span>Barcode: <span className="font-mono text-secondary">{selectedProduct.product_code}</span></span>
                                    <span>{selectedProduct.annotation_count} annotations in training data</span>
                                    <span>{selectedProduct.corrected_count} corrected</span>
                                </div>
                            </div>

                            {/* View selector tabs */}
                            <div className="flex gap-1 px-4 py-2 border-b border-border/60">
                                {VIEW_ORDER.filter((v) => selectedProduct.image_types.includes(v)).map((view) => (
                                    <button
                                        key={view}
                                        onClick={() => setSelectedView(view)}
                                        className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                                            selectedView === view
                                                ? 'bg-primary text-white'
                                                : 'text-secondary hover:bg-surface-dim hover:text-foreground'
                                        }`}
                                    >
                                        {view}
                                    </button>
                                ))}
                            </div>

                            {/* Image display */}
                            <div className="flex-1 flex items-center justify-center p-4 bg-white dark:bg-surface-dim">
                                <img
                                    src={`${API}/dataset/products/${selectedProduct.product_code}/${selectedView}.jpg`}
                                    alt={`${selectedProduct.product_name} - ${selectedView}`}
                                    className="max-h-full max-w-full object-contain"
                                    style={{ maxHeight: 'calc(100vh - 340px)' }}
                                />
                            </div>

                            {/* All views thumbnail strip */}
                            <div className="flex gap-2 px-4 py-3 border-t border-border/60 overflow-x-auto">
                                {VIEW_ORDER.filter((v) => selectedProduct.image_types.includes(v)).map((view) => (
                                    <button
                                        key={view}
                                        onClick={() => setSelectedView(view)}
                                        className={`flex-shrink-0 rounded border-2 transition-colors overflow-hidden ${
                                            selectedView === view ? 'border-primary' : 'border-transparent hover:border-border'
                                        }`}
                                    >
                                        <img
                                            src={`${API}/dataset/products/${selectedProduct.product_code}/${view}.jpg`}
                                            alt={view}
                                            className="w-16 h-16 object-contain bg-white"
                                        />
                                    </button>
                                ))}
                            </div>
                        </>
                    ) : (
                        <div className="flex-1 flex flex-col items-center justify-center text-muted gap-2">
                            <Package className="w-10 h-10" />
                            <span className="text-sm">Select a product to view reference images</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
