import { type ReactNode, useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface Column<T> {
    key: string;
    label: string;
    render?: (item: T) => ReactNode;
    width?: string;
}

interface TableProps<T> {
    columns: Column<T>[];
    data: T[];
    onRowClick?: (item: T) => void;
    emptyMessage?: string;
    getRowKey?: (item: T) => string | number;
    paginated?: boolean;
    pageSize?: number;
    currentPage?: number;
    totalItems?: number;
    onPageChange?: (page: number) => void;
}

export function Table<T>({
    columns,
    data,
    onRowClick,
    emptyMessage = 'No data available',
    getRowKey = (item: any) => item.id,
    paginated = false,
    pageSize = 20,
    currentPage: externalCurrentPage,
    totalItems: externalTotalItems,
    onPageChange: externalOnPageChange,
}: TableProps<T>) {
    const [internalCurrentPage, setInternalCurrentPage] = useState(1);

    const currentPage = externalCurrentPage ?? internalCurrentPage;
    const onPageChange = externalOnPageChange ?? setInternalCurrentPage;

    const displayData = useMemo(() => {
        if (!paginated || externalTotalItems !== undefined) return data;
        const start = (currentPage - 1) * pageSize;
        return data.slice(start, start + pageSize);
    }, [data, paginated, currentPage, pageSize, externalTotalItems]);

    const totalItems = externalTotalItems ?? data.length;

    return (
        <div className="w-full">
            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead>
                        <tr>
                            {columns.map((col) => (
                                <th
                                    key={col.key}
                                    className="text-left py-3 px-6 font-medium text-secondary whitespace-nowrap"
                                    style={{ width: col.width }}
                                >
                                    {col.label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {displayData.length === 0 ? (
                            <tr>
                                <td colSpan={columns.length} className="px-6 py-12 text-center">
                                    <p className="text-sm text-secondary">{emptyMessage}</p>
                                </td>
                            </tr>
                        ) : (
                            displayData.map((item) => (
                                <tr
                                    key={getRowKey(item)}
                                    onClick={() => onRowClick?.(item)}
                                    className={cn(
                                        'border-t border-border transition-colors',
                                        onRowClick && 'cursor-pointer hover:bg-muted/20'
                                    )}
                                >
                                    {columns.map((col) => {
                                        const content = col.render
                                            ? col.render(item)
                                            : (item as any)[col.key];
                                        return (
                                            <td key={col.key} className="py-4 px-6 text-secondary" style={{ width: col.width }}>
                                                <div className="truncate">{content ?? '-'}</div>
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {paginated && (
                <Pagination
                    currentPage={currentPage}
                    pageSize={pageSize}
                    totalItems={totalItems}
                    onPageChange={onPageChange}
                />
            )}
        </div>
    );
}

interface PaginationProps {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    onPageChange: (page: number) => void;
}

function Pagination({ currentPage, pageSize, totalItems, onPageChange }: PaginationProps) {
    const totalPages = Math.ceil(totalItems / pageSize);
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    const endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    const pages = [];
    for (let i = startPage; i <= endPage; i++) {
        pages.push(i);
    }

    return (
        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
            <div className="text-sm text-secondary">
                Showing {totalItems === 0 ? 0 : (currentPage - 1) * pageSize + 1} to{' '}
                {Math.min(currentPage * pageSize, totalItems)} of {totalItems}
            </div>
            <div className="flex items-center gap-2">
                <button
                    onClick={() => onPageChange(currentPage - 1)}
                    disabled={currentPage === 1}
                    className={cn(
                        'p-2 rounded-xl transition-all duration-200 text-secondary',
                        currentPage === 1 ? 'opacity-30 cursor-not-allowed' : 'hover:bg-surface hover:text-foreground'
                    )}
                >
                    <ChevronLeft className="w-4 h-4" />
                </button>
                <div className="flex items-center gap-1.5">
                    {pages.map((p) => (
                        <button
                            key={p}
                            onClick={() => onPageChange(p)}
                            className={cn(
                                'min-w-[36px] h-9 px-3 rounded-xl transition-all duration-200 text-sm font-semibold',
                                p === currentPage
                                    ? 'bg-primary text-white shadow-lg shadow-primary/25'
                                    : 'text-secondary hover:bg-surface hover:text-foreground'
                            )}
                        >
                            {p}
                        </button>
                    ))}
                </div>
                <button
                    onClick={() => onPageChange(currentPage + 1)}
                    disabled={currentPage >= totalPages}
                    className={cn(
                        'p-2 rounded-xl transition-all duration-200 text-secondary',
                        currentPage >= totalPages ? 'opacity-30 cursor-not-allowed' : 'hover:bg-surface hover:text-foreground'
                    )}
                >
                    <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
}
