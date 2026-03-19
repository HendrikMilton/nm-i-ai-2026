import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, type Column } from '../components/ui/Table';
import { ChallengeFilter } from '../components/ui/ChallengeFilter';
import { Badge } from '../components/ui/Badge';
import { type LogEntry, fetchLogs } from '../api/logs';

const PAGE_SIZE = 20;

const columns: Column<LogEntry>[] = [
    {
        key: 'challenge',
        label: 'Challenge',
        width: '120px',
        render: (item) => <Badge>Challenge {item.challenge}</Badge>,
    },
    {
        key: 'index',
        label: '#',
        width: '80px',
        render: (item) => <span className="text-foreground font-mono">{item.index}</span>,
    },
    {
        key: 'ts',
        label: 'Time',
        width: '200px',
        render: (item) => (
            <span className="text-foreground text-xs">
                {new Date(item.ts * 1000).toLocaleString()}
            </span>
        ),
    },
    {
        key: 'elapsed',
        label: 'Latency',
        width: '120px',
        render: (item) => {
            const ms = item.elapsed * 1000;
            const variant = ms > 1000 ? 'error' : ms > 300 ? 'warning' : 'success';
            return <Badge variant={variant}>{ms.toFixed(0)}ms</Badge>;
        },
    },
    {
        key: 'request',
        label: 'Request (preview)',
        render: (item) => (
            <span className="text-xs font-mono text-secondary truncate block max-w-[400px]">
                {JSON.stringify(item.request).slice(0, 100)}...
            </span>
        ),
    },
];

export function LogsPage() {
    const navigate = useNavigate();
    const [challengeFilter, setChallengeFilter] = useState<number | null>(null);
    const [page, setPage] = useState(1);
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);

    const loadLogs = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetchLogs({
                challenge: challengeFilter ?? undefined,
                page,
                pageSize: PAGE_SIZE,
            });
            setLogs(res.logs);
            setTotal(res.total);
        } catch (err) {
            console.error('Failed to fetch logs:', err);
        } finally {
            setLoading(false);
        }
    }, [challengeFilter, page]);

    useEffect(() => {
        loadLogs();
    }, [loadLogs]);

    useEffect(() => {
        setPage(1);
    }, [challengeFilter]);

    return (
        <div>
            <div className="flex items-center justify-between mb-6">
                <h1 className="text-xl font-semibold text-foreground">Debug Logs</h1>
                <ChallengeFilter selected={challengeFilter} onChange={setChallengeFilter} />
            </div>

            <div className="bg-surface rounded-lg border border-border/60 shadow-gcp">
                {loading && logs.length === 0 ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
                    </div>
                ) : (
                    <Table
                        columns={columns}
                        data={logs}
                        getRowKey={(item) => `${item.challenge}-${item.index}`}
                        onRowClick={(item) => navigate(`/replay/${item.challenge}/${item.index}`)}
                        paginated
                        currentPage={page}
                        pageSize={PAGE_SIZE}
                        totalItems={total}
                        onPageChange={setPage}
                        emptyMessage="No logs yet. Run some requests against the challenges first."
                    />
                )}
            </div>
        </div>
    );
}
