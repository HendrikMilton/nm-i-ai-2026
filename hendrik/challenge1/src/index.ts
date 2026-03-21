import express from 'express';
import { solve } from './agent';
import { writeFileSync, appendFileSync, mkdirSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const LB_DIR = join(__dirname, '..', 'leaderboard_jsons');
const LOGS_DIR = join(__dirname, '..', 'logs');
const LB_URL = 'https://api.ainm.no/tripletex/leaderboard/99677c07-5ebd-48f1-8592-e1528a2d77ef';

mkdirSync(LB_DIR, { recursive: true });

async function fetchLeaderboard(): Promise<any[]> {
    try {
        const res = await fetch(LB_URL);
        return await res.json() as any[];
    } catch {
        return [];
    }
}

function latestLogFile(): string | null {
    try {
        const files = readdirSync(LOGS_DIR).filter(f => f.endsWith('.log')).sort().reverse();
        return files[0] ? join(LOGS_DIR, files[0]) : null;
    } catch {
        return null;
    }
}

function diffLeaderboard(before: any[], after: any[]): string | null {
    const beforeMap = new Map(before.map((t: any) => [t.tx_task_id, t]));
    const changes: string[] = [];
    let taskId = '';

    for (const a of after) {
        const b = beforeMap.get(a.tx_task_id);
        if (!b) continue;
        if (a.best_score !== b.best_score) {
            changes.push(`Task ${a.tx_task_id}: ${b.best_score} → ${a.best_score} (${a.best_score > b.best_score ? '+' : ''}${(a.best_score - b.best_score).toFixed(2)})`);
        }
        if (a.total_attempts !== b.total_attempts) {
            taskId = a.tx_task_id;
        }
    }

    if (!taskId && changes.length === 0) return null;

    const totalBefore = before.reduce((s: number, t: any) => s + (t.best_score || 0), 0);
    const totalAfter = after.reduce((s: number, t: any) => s + (t.best_score || 0), 0);

    const lines = [
        `\n[LEADERBOARD] Task ${taskId} scored`,
        ...changes.map(c => `[LEADERBOARD] ${c}`),
        `[LEADERBOARD] Total: ${totalBefore.toFixed(2)} → ${totalAfter.toFixed(2)} (${totalAfter > totalBefore ? '+' : ''}${(totalAfter - totalBefore).toFixed(2)})`,
    ];
    return lines.join('\n');
}

async function pollForChange(before: any[], ts: string) {
    const maxAttempts = 24; // 24 × 10s = 4 minutes
    for (let i = 0; i < maxAttempts; i++) {
        await new Promise(r => setTimeout(r, 10_000));
        try {
            const after = await fetchLeaderboard();
            if (after.length === 0) continue;

            // Check if attempts changed (meaning scoring happened)
            const beforeAttempts = before.reduce((s: number, t: any) => s + (t.total_attempts || 0), 0);
            const afterAttempts = after.reduce((s: number, t: any) => s + (t.total_attempts || 0), 0);
            if (afterAttempts <= beforeAttempts) continue;

            // Save after state
            writeFileSync(join(LB_DIR, `${ts}-after.json`), JSON.stringify(after, null, 2));

            // Diff and append to log
            const diff = diffLeaderboard(before, after);
            if (diff) {
                const logFile = latestLogFile();
                if (logFile) {
                    appendFileSync(logFile, diff + '\n');
                    console.log(diff);
                }
            }
            return;
        } catch {}
    }
}

const app = express();
app.use(express.json({ limit: '50mb' }));

app.get('/', (_req, res) => {
    res.json({ status: 'ok', challenge: 1 });
});

app.post('/solve', async (req, res) => {
    const start = Date.now();
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    console.log(`[SOLVE] received prompt: ${req.body.prompt?.slice(0, 100)}...`);

    // Fetch leaderboard state before solving
    const before = await fetchLeaderboard();
    if (before.length > 0) {
        writeFileSync(join(LB_DIR, `${ts}-before.json`), JSON.stringify(before, null, 2));
    }

    try {
        await solve(req.body);
        const elapsed = ((Date.now() - start) / 1000).toFixed(1);
        console.log(`[SOLVE] completed in ${elapsed}s`);
        res.json({ status: 'completed' });
    } catch (err) {
        const elapsed = ((Date.now() - start) / 1000).toFixed(1);
        console.error(`[SOLVE] failed after ${elapsed}s:`, err);
        res.json({ status: 'completed' });
    }

    // Start background polling (non-blocking)
    if (before.length > 0) {
        pollForChange(before, ts).catch(() => {});
    }
});

const port = Number(process.env.PORT ?? 4001);
app.listen(port, () => console.log(`Challenge 1 listening on :${port}`));
