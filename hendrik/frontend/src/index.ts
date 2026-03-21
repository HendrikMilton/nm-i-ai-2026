import { serve } from 'bun';
import { readdir, readFile } from 'fs/promises';
import { join } from 'path';
import index from './index.html';

const CHALLENGE3_DIR = join(import.meta.dir, '../../challenge3/round_data');

const server = serve({
    port: 3002,
    routes: {
        '/api/challenge3/rounds': async () => {
            try {
                const files = await readdir(CHALLENGE3_DIR);
                const rounds = files
                    .filter(f => f.match(/^round_\d+_submit\.json$/))
                    .map(f => Number(f.match(/round_(\d+)_submit/)?.[1]))
                    .filter(n => !isNaN(n))
                    .sort((a, b) => a - b);
                return Response.json(rounds);
            } catch {
                return Response.json([]);
            }
        },
        '/api/challenge3/round/:num': async (req) => {
            try {
                const num = (req as any).params.num;
                const padded = String(num).padStart(2, '0');
                const data = await readFile(join(CHALLENGE3_DIR, `round_${padded}_submit.json`), 'utf-8');
                return new Response(data, { headers: { 'Content-Type': 'application/json' } });
            } catch {
                return new Response('Not found', { status: 404 });
            }
        },
        '/*': index,
    },
    development: process.env.NODE_ENV !== 'production' && {
        hmr: true,
        console: true,
    },
});

console.log(`Server running at ${server.url}`);
