/**
 * API server that reads requests.jsonl from challenge folders.
 * Runs alongside the frontend dev server on port 3003.
 */
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const CHALLENGES_DIR = join(import.meta.dir, '../../');
const PORT = 3003;

interface LogEntry {
    ts: number;
    elapsed: number;
    request: Record<string, unknown>;
    response: Record<string, unknown>;
}

function readLogs(challenge: number): (LogEntry & { challenge: number; index: number })[] {
    const path = join(CHALLENGES_DIR, `challenge${challenge}`, 'requests.jsonl');
    if (!existsSync(path)) return [];
    const lines = readFileSync(path, 'utf-8').trim().split('\n').filter(Boolean);
    return lines.map((line, index) => {
        const entry = JSON.parse(line) as LogEntry;
        return { ...entry, challenge, index };
    });
}

function getAllLogs(challengeFilter?: number) {
    const challenges = challengeFilter ? [challengeFilter] : [1, 2, 3];
    const all = challenges.flatMap(readLogs);
    all.sort((a, b) => b.ts - a.ts); // newest first
    return all;
}

const server = Bun.serve({
    port: PORT,
    async fetch(req) {
        const url = new URL(req.url);
        const headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        };

        if (req.method === 'OPTIONS') {
            return new Response(null, { headers });
        }

        // GET /logs?challenge=1&page=1&pageSize=20
        if (url.pathname === '/logs') {
            const challenge = url.searchParams.get('challenge');
            const page = Number(url.searchParams.get('page') || 1);
            const pageSize = Number(url.searchParams.get('pageSize') || 20);

            const all = getAllLogs(challenge ? Number(challenge) : undefined);
            const start = (page - 1) * pageSize;
            const logs = all.slice(start, start + pageSize);

            return Response.json({ logs, total: all.length, page, pageSize }, { headers });
        }

        // GET /logs/:challenge/:index
        const match = url.pathname.match(/^\/logs\/(\d+)\/(\d+)$/);
        if (match) {
            const challenge = Number(match[1]);
            const index = Number(match[2]);
            const logs = readLogs(challenge);
            const entry = logs.find((e) => e.index === index);
            if (!entry) {
                return Response.json({ error: 'Not found' }, { status: 404, headers });
            }
            return Response.json(entry, { headers });
        }

        return Response.json({ error: 'Not found' }, { status: 404, headers });
    },
});

console.log(`API server running at http://localhost:${PORT}`);
