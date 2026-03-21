import { appendFileSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { generateText, type LanguageModel } from 'ai';
import { createVertex } from '@ai-sdk/google-vertex';
import { createVertexAnthropic } from '@ai-sdk/google-vertex/anthropic';
import { TripletexClient } from './tripletex';
import { createTools } from './tools';
import { SYSTEM_PROMPT } from './system-prompt';
import { GCP_PROJECT, GCP_LOCATION, GCP_LOCATION_ANTHROPIC } from './config';

const MODEL = process.env.MODEL ?? 'claude-opus-4-6';
const __dirname = dirname(fileURLToPath(import.meta.url));
const LOGS_DIR = join(__dirname, '..', 'logs');

const createLogger = () => {
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const logFile = join(LOGS_DIR, `${ts}.log`);
    return (msg: string) => {
        const line = `[${new Date().toISOString()}] ${msg}`;
        console.log(line);
        appendFileSync(logFile, line + '\n');
    };
};

const vertex = createVertex({ project: GCP_PROJECT, location: GCP_LOCATION });
const vertexAnthropic = createVertexAnthropic({ project: GCP_PROJECT, location: GCP_LOCATION_ANTHROPIC });

const getModel = (id: string): LanguageModel => {
    if (id.startsWith('claude-')) {
        return vertexAnthropic(id);
    }
    return vertex(id);
};

interface SolveRequest {
  prompt: string;
  files?: { filename: string; content_base64: string; mime_type: string }[];
  tripletex_credentials: {
    base_url: string;
    session_token: string;
  };
}

export const solve = async (body: SolveRequest) => {
    const log = createLogger();
    const start = Date.now();
    const { prompt, files, tripletex_credentials } = body;
    const client = new TripletexClient(tripletex_credentials.base_url, tripletex_credentials.session_token);
    client.onLog = (msg) => log(msg);
    const tools = createTools(client);

    const today = new Date().toISOString().split('T')[0];

    log(`[AGENT] model=${MODEL} prompt="${prompt}"`);

    // Build user message content
    const userContent: Array<
    | { type: 'text'; text: string }
    | { type: 'image'; image: string; mimeType?: string }
  > = [];

    if (files?.length) {
        // Save attachments to disk for debugging
        const ts = new Date().toISOString().replace(/[:.]/g, '-');
        const attachDir = join(__dirname, '..', 'logs', 'attachments', ts);
        mkdirSync(attachDir, { recursive: true });
        for (const f of files) {
            const filePath = join(attachDir, f.filename);
            mkdirSync(dirname(filePath), { recursive: true });
            writeFileSync(filePath, Buffer.from(f.content_base64, 'base64'));
            log(`[AGENT] saved attachment: ${join(attachDir, f.filename)}`);
        }
        for (const f of files) {
            if (f.mime_type.startsWith('image/')) {
                userContent.push({
                    type: 'image',
                    image: `data:${f.mime_type};base64,${f.content_base64}`,
                });
            } else if (f.mime_type === 'application/pdf') {
                userContent.push({
                    type: 'file',
                    data: f.content_base64,
                    mimeType: f.mime_type,
                } as any);
            } else {
                userContent.push({
                    type: 'text',
                    text: `[Attached file: ${f.filename} (${f.mime_type}), base64 length: ${f.content_base64.length}]`,
                });
            }
        }
        log(`[AGENT] files: ${files.map(f => f.filename).join(', ')}`);
    }

    userContent.push({
        type: 'text',
        text: `Today's date: ${today}\n\nTask:\n${prompt}`,
    });

    const abortController = new AbortController();
    const timeout = setTimeout(() => {
        log('[AGENT] TIMEOUT — aborting after 240s');
        abortController.abort();
    }, 240_000);

    let result;
    try {
        result = await generateText({
            model: getModel(MODEL),
            system: SYSTEM_PROMPT,
            messages: [{ role: 'user', content: userContent }],
            tools,
            maxSteps: 25,
            abortSignal: abortController.signal,
        });
    } finally {
        clearTimeout(timeout);
    }

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    const apiCalls = client.callLog.length;
    const errors = client.callLog.filter(c => c.status >= 400).length;

    // Log step details
    for (let i = 0; i < result.steps.length; i++) {
        const step = result.steps[i];
        const toolCalls = step.toolCalls?.map(tc => `${tc.toolName}(${JSON.stringify(tc.args)})`).join(', ') || '';
        const toolResults = step.toolResults?.map(tr => `${tr.toolName}→${JSON.stringify(tr.result)}`).join(', ') || '';
        if (toolCalls) {
            log(`[STEP ${i + 1}] calls: ${toolCalls}`);
        }
        if (toolResults) {
            log(`[STEP ${i + 1}] results: ${toolResults}`);
        }
        if (step.text) {
            log(`[STEP ${i + 1}] text: ${step.text}`);
        }
    }

    log(`[AGENT] DONE elapsed=${elapsed}s steps=${result.steps.length} apiCalls=${apiCalls} errors=${errors}`);
    log(`[AGENT] apiLog: ${JSON.stringify(client.callLog)}`);
    log(`[AGENT] response: ${result.text}`);
    log('---');
};
