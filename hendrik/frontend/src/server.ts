/**
 * API server that reads requests.jsonl from challenge folders
 * and serves dataset images + annotations.
 * Runs alongside the frontend dev server on port 3003.
 */
import { readFileSync, existsSync } from 'fs';
import { join, extname } from 'path';

const CHALLENGES_DIR = join(import.meta.dir, '../../');
const HOME = process.env.HOME || '/home/hendrik';
const DATASET_DIR = join(HOME, 'NM_NGD_coco_dataset/train');
const PRODUCT_IMAGES_DIR = join(HOME, 'NM_NGD_product_images');
const PORT = 3003;

const MIME: Record<string, string> = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.json': 'application/json',
};

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

        // GET /dataset/annotations
        if (url.pathname === '/dataset/annotations') {
            const path = join(DATASET_DIR, 'annotations.json');
            if (!existsSync(path)) {
                return Response.json({ error: 'annotations.json not found' }, { status: 404, headers });
            }
            return new Response(readFileSync(path), {
                headers: { ...headers, 'Content-Type': 'application/json' },
            });
        }

        // GET /dataset/images/:filename
        const imgMatch = url.pathname.match(/^\/dataset\/images\/(.+)$/);
        if (imgMatch) {
            const filename = imgMatch[1];
            // Prevent path traversal
            if (filename.includes('..') || filename.includes('/')) {
                return Response.json({ error: 'Invalid filename' }, { status: 400, headers });
            }
            const imgPath = join(DATASET_DIR, 'images', filename);
            if (!existsSync(imgPath)) {
                return Response.json({ error: 'Image not found' }, { status: 404, headers });
            }
            const ext = extname(filename).toLowerCase();
            return new Response(Bun.file(imgPath), {
                headers: { ...headers, 'Content-Type': MIME[ext] || 'application/octet-stream', 'Cache-Control': 'public, max-age=86400' },
            });
        }

        // GET /dataset/products/:barcode/:view (e.g. /dataset/products/7071848003921/main.jpg)
        const prodMatch = url.pathname.match(/^\/dataset\/products\/([^/]+)\/([^/]+)$/);
        if (prodMatch) {
            const [, barcode, view] = prodMatch;
            if (barcode.includes('..') || view.includes('..')) {
                return Response.json({ error: 'Invalid path' }, { status: 400, headers });
            }
            const prodPath = join(PRODUCT_IMAGES_DIR, barcode, view);
            if (!existsSync(prodPath)) {
                return Response.json({ error: 'Product image not found' }, { status: 404, headers });
            }
            const ext = extname(view).toLowerCase();
            return new Response(Bun.file(prodPath), {
                headers: { ...headers, 'Content-Type': MIME[ext] || 'application/octet-stream', 'Cache-Control': 'public, max-age=86400' },
            });
        }

        // GET /predictions/list — list available prediction runs
        if (url.pathname === '/predictions/list') {
            const runsDir = join(CHALLENGES_DIR, 'challenge2', 'runs');
            if (!existsSync(runsDir)) {
                return Response.json({ runs: [] }, { headers });
            }
            const { readdirSync } = await import('fs');
            const dirs = readdirSync(runsDir, { withFileTypes: true })
                .filter((d) => d.isDirectory())
                .map((d) => d.name)
                .filter((name) => existsSync(join(runsDir, name, 'all_predictions.json')));
            return Response.json({ runs: dirs }, { headers });
        }

        // GET /predictions/:run — serve predictions for a run
        const predMatch = url.pathname.match(/^\/predictions\/([^/]+)$/);
        if (predMatch) {
            const runName = predMatch[1];
            if (runName.includes('..')) {
                return Response.json({ error: 'Invalid run name' }, { status: 400, headers });
            }
            const path = join(CHALLENGES_DIR, 'challenge2', 'runs', runName, 'all_predictions.json');
            if (!existsSync(path)) {
                return Response.json({ error: 'Predictions not found' }, { status: 404, headers });
            }
            return new Response(readFileSync(path), {
                headers: { ...headers, 'Content-Type': 'application/json' },
            });
        }

        // GET /training/logs — read training_logs.jsonl
        if (url.pathname === '/training/logs') {
            const path = join(CHALLENGES_DIR, 'challenge2', 'training_logs.jsonl');
            if (!existsSync(path)) {
                return Response.json({ logs: [] }, { headers });
            }
            const lines = readFileSync(path, 'utf-8').trim().split('\n').filter(Boolean);
            const logs = lines.map((line) => JSON.parse(line));
            return Response.json({ logs }, { headers });
        }

        // GET /dataset/product-metadata
        if (url.pathname === '/dataset/product-metadata') {
            const path = join(PRODUCT_IMAGES_DIR, 'metadata.json');
            if (!existsSync(path)) {
                return Response.json({ error: 'metadata.json not found' }, { status: 404, headers });
            }
            return new Response(readFileSync(path), {
                headers: { ...headers, 'Content-Type': 'application/json' },
            });
        }

        return Response.json({ error: 'Not found' }, { status: 404, headers });
    },
});

console.log(`API server running at http://localhost:${PORT}`);
