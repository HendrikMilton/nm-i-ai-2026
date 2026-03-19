import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '../../lib/utils';

interface JsonViewerProps {
    data: unknown;
    label?: string;
    defaultExpanded?: boolean;
}

export function JsonViewer({ data, label, defaultExpanded = true }: JsonViewerProps) {
    const [expanded, setExpanded] = useState(defaultExpanded);

    if (data === null || data === undefined) {
        return <span className="text-muted font-mono text-sm">null</span>;
    }

    if (typeof data !== 'object') {
        return (
            <span className={cn(
                'font-mono text-sm',
                typeof data === 'string' ? 'text-success' : 'text-primary'
            )}>
                {typeof data === 'string' ? `"${data}"` : String(data)}
            </span>
        );
    }

    const entries = Array.isArray(data)
        ? data.map((v, i) => [String(i), v] as const)
        : Object.entries(data);

    const bracket = Array.isArray(data) ? ['[', ']'] : ['{', '}'];

    return (
        <div className="font-mono text-sm">
            <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1 hover:text-primary transition-colors"
            >
                {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {label && <span className="text-foreground font-medium">{label}</span>}
                <span className="text-secondary">
                    {bracket[0]}{!expanded && `...${bracket[1]}`}
                    {!expanded && <span className="text-muted ml-1">({entries.length})</span>}
                </span>
            </button>
            {expanded && (
                <div className="ml-4 border-l border-border/40 pl-3">
                    {entries.map(([key, value]) => (
                        <div key={key} className="py-0.5">
                            {typeof value === 'object' && value !== null ? (
                                <JsonViewer data={value} label={`${key}:`} defaultExpanded={false} />
                            ) : (
                                <div className="flex items-center gap-2">
                                    <span className="text-foreground">{key}:</span>
                                    <JsonViewer data={value} />
                                </div>
                            )}
                        </div>
                    ))}
                    <span className="text-secondary">{bracket[1]}</span>
                </div>
            )}
        </div>
    );
}
