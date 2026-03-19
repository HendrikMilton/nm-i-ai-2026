import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { JsonViewer } from '../components/ui/JsonViewer';
import { type LogEntry, fetchLogEntry } from '../api/logs';

export function ReplayPage() {
    const { challenge, index } = useParams<{ challenge: string; index: string }>();
    const navigate = useNavigate();
    const [entry, setEntry] = useState<LogEntry | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!challenge || !index) return;
        setLoading(true);
        setError(null);
        fetchLogEntry(Number(challenge), Number(index))
            .then(setEntry)
            .catch((err) => setError(err.message ?? 'Failed to load'))
            .finally(() => setLoading(false));
    }, [challenge, index]);

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
            </div>
        );
    }

    if (error || !entry) {
        return (
            <div className="text-center py-20">
                <p className="text-error mb-4">{error ?? 'Entry not found'}</p>
                <Button onClick={() => navigate('/logs')}>Back to logs</Button>
            </div>
        );
    }

    const ms = entry.elapsed * 1000;

    return (
        <div>
            <div className="flex items-center gap-4 mb-6">
                <Button variant="ghost" onClick={() => navigate('/logs')}>
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Back
                </Button>
                <h1 className="text-xl font-semibold text-foreground">
                    Replay
                </h1>
                <Badge>Challenge {entry.challenge}</Badge>
                <span className="text-sm text-secondary">#{entry.index}</span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <RequestCard entry={entry} />
                <ResponseCard entry={entry} ms={ms} />
            </div>

            <MetadataBar entry={entry} ms={ms} />
        </div>
    );
}

function RequestCard({ entry }: { entry: LogEntry }) {
    return (
        <div className="bg-surface rounded-lg border border-border/60 shadow-gcp overflow-hidden">
            <div className="px-6 py-4 border-b border-border/60">
                <h2 className="text-sm font-semibold text-foreground">Request</h2>
            </div>
            <div className="p-6 max-h-[600px] overflow-auto">
                <JsonViewer data={entry.request} />
            </div>
        </div>
    );
}

function ResponseCard({ entry, ms }: { entry: LogEntry; ms: number }) {
    const variant = ms > 1000 ? 'error' : ms > 300 ? 'warning' : 'success';
    return (
        <div className="bg-surface rounded-lg border border-border/60 shadow-gcp overflow-hidden">
            <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-foreground">Response</h2>
                <Badge variant={variant}>{ms.toFixed(0)}ms</Badge>
            </div>
            <div className="p-6 max-h-[600px] overflow-auto">
                <JsonViewer data={entry.response} />
            </div>
        </div>
    );
}

function MetadataBar({ entry, ms }: { entry: LogEntry; ms: number }) {
    return (
        <div className="mt-6 bg-surface rounded-lg border border-border/60 shadow-gcp px-6 py-4 flex items-center gap-8 text-sm">
            <div>
                <span className="text-secondary">Timestamp: </span>
                <span className="text-foreground font-mono">
                    {new Date(entry.ts * 1000).toLocaleString()}
                </span>
            </div>
            <div>
                <span className="text-secondary">Latency: </span>
                <span className="text-foreground font-mono">{ms.toFixed(2)}ms</span>
            </div>
            <div>
                <span className="text-secondary">Challenge: </span>
                <span className="text-foreground font-mono">{entry.challenge}</span>
            </div>
            <div>
                <span className="text-secondary">Index: </span>
                <span className="text-foreground font-mono">{entry.index}</span>
            </div>
        </div>
    );
}
