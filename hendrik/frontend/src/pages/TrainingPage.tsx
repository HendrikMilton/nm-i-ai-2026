import { useState, useEffect, useMemo } from 'react';
import { RefreshCw } from 'lucide-react';
import { Table, type Column } from '../components/ui/Table';
import { Breadcrumbs } from '../components/Breadcrumbs';
import { Badge } from '../components/ui/Badge';

const API = 'http://localhost:3003';

interface LogEntry {
    ts: number;
    time: string;
    run: string;
    event: string;
    [key: string]: unknown;
}

interface RunSummary {
    name: string;
    status: 'training' | 'complete' | 'evaluated';
    model: string;
    startTime: string;
    duration?: string;
    lastEpoch?: number;
    totalEpochs?: number;
    mAP50?: number;
    mAP50_95?: number;
    precision?: number;
    recall?: number;
    // eval results
    score?: number;
    detectionMAP?: number;
    classificationMAP?: number;
    numPredictions?: number;
    // config
    imgsz?: number;
    batch?: number;
}

interface EpochData {
    epoch: number;
    loss: number;
    box_loss: number;
    cls_loss: number;
    mAP50: number;
    mAP50_95: number;
}

function buildRunSummaries(logs: LogEntry[]): RunSummary[] {
    const runs = new Map<string, RunSummary>();
    const epochs = new Map<string, EpochData[]>();

    for (const log of logs) {
        const name = log.run;
        if (!runs.has(name)) {
            runs.set(name, { name, status: 'training', model: '', startTime: '' });
            epochs.set(name, []);
        }
        const run = runs.get(name)!;

        if (log.event === 'start') {
            run.model = log.model as string || '';
            run.startTime = log.time;
            run.imgsz = log.imgsz as number;
            run.batch = log.batch as number;
            run.totalEpochs = log.epochs as number;
        } else if (log.event === 'epoch') {
            const ep: EpochData = {
                epoch: log.epoch as number,
                loss: log.loss as number,
                box_loss: log.box_loss as number,
                cls_loss: log.cls_loss as number,
                mAP50: log.mAP50 as number,
                mAP50_95: log.mAP50_95 as number,
            };
            epochs.get(name)!.push(ep);
            run.lastEpoch = ep.epoch;
            run.mAP50 = ep.mAP50;
            run.mAP50_95 = ep.mAP50_95;
        } else if (log.event === 'complete') {
            run.status = 'complete';
            run.duration = `${((log.duration_s as number) / 60).toFixed(1)} min`;
            run.mAP50 = log.mAP50 as number;
            run.mAP50_95 = log.mAP50_95 as number;
            run.precision = log.precision as number;
            run.recall = log.recall as number;
        } else if (log.event === 'eval') {
            run.status = 'evaluated';
            run.score = log.score as number;
            run.detectionMAP = log.detection_mAP as number;
            run.classificationMAP = log.classification_mAP as number;
            run.numPredictions = log.num_predictions as number;
        }
    }

    return Array.from(runs.values()).reverse(); // newest first
}

const statusVariant = (s: string): 'default' | 'success' | 'warning' | 'error' => {
    if (s === 'evaluated') return 'success';
    if (s === 'complete') return 'warning';
    return 'default';
};

const runColumns: Column<RunSummary>[] = [
    {
        key: 'name',
        label: 'Run',
        width: '180px',
        render: (r) => <span className="font-mono text-foreground font-medium">{r.name}</span>,
    },
    {
        key: 'status',
        label: 'Status',
        width: '100px',
        render: (r) => <Badge variant={statusVariant(r.status)}>{r.status}</Badge>,
    },
    {
        key: 'model',
        label: 'Model',
        width: '120px',
        render: (r) => <span className="text-xs font-mono text-secondary">{r.model}</span>,
    },
    {
        key: 'progress',
        label: 'Progress',
        width: '100px',
        render: (r) => (
            <span className="text-xs font-mono text-secondary">
                {r.lastEpoch ?? '-'}/{r.totalEpochs ?? '-'}
            </span>
        ),
    },
    {
        key: 'mAP50',
        label: 'mAP@0.5',
        width: '90px',
        render: (r) => (
            <span className="font-mono text-foreground font-medium">
                {r.mAP50 != null ? r.mAP50.toFixed(4) : '-'}
            </span>
        ),
    },
    {
        key: 'score',
        label: 'Score',
        width: '90px',
        render: (r) => (
            <span className={`font-mono font-bold ${r.score != null ? 'text-primary' : 'text-muted'}`}>
                {r.score != null ? r.score.toFixed(4) : '-'}
            </span>
        ),
    },
    {
        key: 'detectionMAP',
        label: 'Det mAP',
        width: '90px',
        render: (r) => (
            <span className="font-mono text-secondary">
                {r.detectionMAP != null ? r.detectionMAP.toFixed(4) : '-'}
            </span>
        ),
    },
    {
        key: 'classificationMAP',
        label: 'Cls mAP',
        width: '90px',
        render: (r) => (
            <span className="font-mono text-secondary">
                {r.classificationMAP != null ? r.classificationMAP.toFixed(4) : '-'}
            </span>
        ),
    },
    {
        key: 'duration',
        label: 'Duration',
        width: '90px',
        render: (r) => <span className="text-xs text-secondary">{r.duration ?? '-'}</span>,
    },
];

export function TrainingPage() {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedRun, setSelectedRun] = useState<string | null>(null);
    const [autoRefresh, setAutoRefresh] = useState(true);

    const fetchLogs = () => {
        fetch(`${API}/training/logs`)
            .then((r) => r.json())
            .then((data) => setLogs(data.logs || []))
            .catch((err) => console.error('Failed to load training logs:', err))
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        fetchLogs();
        if (!autoRefresh) return;
        const interval = setInterval(fetchLogs, 5000);
        return () => clearInterval(interval);
    }, [autoRefresh]);

    const runs = useMemo(() => buildRunSummaries(logs), [logs]);

    const selectedRunData = useMemo(() => {
        if (!selectedRun) return null;
        const epochLogs = logs.filter((l) => l.run === selectedRun && l.event === 'epoch');
        return epochLogs.map((l) => ({
            epoch: l.epoch as number,
            loss: l.loss as number,
            box_loss: l.box_loss as number,
            cls_loss: l.cls_loss as number,
            mAP50: l.mAP50 as number,
            mAP50_95: l.mAP50_95 as number,
        }));
    }, [logs, selectedRun]);

    const epochColumns: Column<EpochData>[] = [
        { key: 'epoch', label: 'Epoch', width: '70px', render: (r) => <span className="font-mono text-foreground">{r.epoch}</span> },
        { key: 'loss', label: 'Loss', width: '90px', render: (r) => <span className="font-mono text-secondary">{r.loss.toFixed(4)}</span> },
        { key: 'box_loss', label: 'Box Loss', width: '90px', render: (r) => <span className="font-mono text-secondary">{r.box_loss.toFixed(4)}</span> },
        { key: 'cls_loss', label: 'Cls Loss', width: '90px', render: (r) => <span className="font-mono text-secondary">{r.cls_loss.toFixed(4)}</span> },
        {
            key: 'mAP50', label: 'mAP@0.5', width: '100px',
            render: (r) => <span className="font-mono text-foreground font-medium">{r.mAP50.toFixed(4)}</span>,
        },
        {
            key: 'mAP50_95', label: 'mAP@0.5:0.95', width: '110px',
            render: (r) => <span className="font-mono text-secondary">{r.mAP50_95.toFixed(4)}</span>,
        },
    ];

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            <Breadcrumbs crumbs={[
                { label: '2 - NorgesGruppen Data', to: '/challenges/2' },
                { label: 'Training Runs' },
            ]} />
            <div className="flex items-center gap-4">
                <h1 className="text-xl font-semibold text-foreground">Training Runs</h1>
                <div className="flex-1" />
                <button
                    onClick={() => setAutoRefresh((p) => !p)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        autoRefresh ? 'bg-primary/10 text-primary' : 'text-secondary hover:text-foreground hover:bg-surface-dim'
                    }`}
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${autoRefresh ? 'animate-spin' : ''}`} style={autoRefresh ? { animationDuration: '3s' } : {}} />
                    Auto-refresh {autoRefresh ? 'on' : 'off'}
                </button>
                <button
                    onClick={fetchLogs}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-secondary hover:text-foreground hover:bg-surface-dim transition-colors"
                >
                    Refresh
                </button>
            </div>

            {/* Runs table */}
            <div className="bg-surface rounded-lg border border-border/60 shadow-gcp">
                <Table
                    columns={runColumns}
                    data={runs}
                    getRowKey={(r) => r.name}
                    onRowClick={(r) => setSelectedRun(selectedRun === r.name ? null : r.name)}
                    emptyMessage="No training runs yet. Start training with: python train.py --name my-run"
                />
            </div>

            {/* Selected run details */}
            {selectedRun && selectedRunData && selectedRunData.length > 0 && (
                <div className="bg-surface rounded-lg border border-border/60 shadow-gcp">
                    <div className="px-6 py-3 border-b border-border/60">
                        <span className="text-sm font-semibold text-foreground">
                            Epoch History: {selectedRun}
                        </span>
                    </div>

                    {/* Simple chart: mAP50 progress as bar chart */}
                    <div className="px-6 py-4 border-b border-border/60">
                        <div className="flex items-end gap-px h-32">
                            {selectedRunData.map((ep) => {
                                const height = Math.max(2, ep.mAP50 * 100);
                                return (
                                    <div
                                        key={ep.epoch}
                                        className="flex-1 bg-primary/60 hover:bg-primary rounded-t transition-colors relative group"
                                        style={{ height: `${height}%` }}
                                        title={`Epoch ${ep.epoch}: mAP50=${ep.mAP50.toFixed(4)}`}
                                    >
                                        <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] font-mono text-muted opacity-0 group-hover:opacity-100 whitespace-nowrap">
                                            {ep.mAP50.toFixed(3)}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                        <div className="flex justify-between mt-1 text-[10px] text-muted">
                            <span>Epoch 1</span>
                            <span>mAP@0.5 progress</span>
                            <span>Epoch {selectedRunData.length}</span>
                        </div>
                    </div>

                    <Table
                        columns={epochColumns}
                        data={selectedRunData}
                        getRowKey={(r) => String(r.epoch)}
                        paginated
                        pageSize={20}
                    />
                </div>
            )}
        </div>
    );
}
