import express from 'express';
import { solve } from './agent';

const app = express();
app.use(express.json({ limit: '50mb' }));

app.get('/', (_req, res) => {
    res.json({ status: 'ok', challenge: 1 });
});

app.post('/solve', async (req, res) => {
    const start = Date.now();
    console.log(`[SOLVE] received prompt: ${req.body.prompt?.slice(0, 100)}...`);

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
});

const port = Number(process.env.PORT ?? 4001);
app.listen(port, () => console.log(`Challenge 1 listening on :${port}`));
