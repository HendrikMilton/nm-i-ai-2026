import { generateText, type LanguageModel } from 'ai';
import { createVertex } from '@ai-sdk/google-vertex';
import { createVertexAnthropic } from '@ai-sdk/google-vertex/anthropic';
import { TripletexClient } from './tripletex';
import { createTools } from './tools';
import { SYSTEM_PROMPT } from './system-prompt';
import { MODEL, GCP_PROJECT, GCP_LOCATION, GCP_LOCATION_ANTHROPIC } from './config';

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
    const { prompt, files, tripletex_credentials } = body;
    const client = new TripletexClient(tripletex_credentials.base_url, tripletex_credentials.session_token);
    const tools = createTools(client);

    const today = new Date().toISOString().split('T')[0];

    // Build user message content
    const userContent: Array<
    | { type: 'text'; text: string }
    | { type: 'image'; image: string; mimeType?: string }
  > = [];

    // Add files as multimodal content
    if (files?.length) {
        for (const f of files) {
            if (f.mime_type.startsWith('image/')) {
                userContent.push({
                    type: 'image',
                    image: `data:${f.mime_type};base64,${f.content_base64}`,
                });
            } else {
                userContent.push({
                    type: 'text',
                    text: `[Attached file: ${f.filename} (${f.mime_type}), base64 length: ${f.content_base64.length}]`,
                });
            }
        }
    }

    userContent.push({
        type: 'text',
        text: `Today's date: ${today}\n\nTask:\n${prompt}`,
    });

    console.log(`[AGENT] Using model: ${MODEL}, prompt: ${prompt.slice(0, 80)}...`);

    const result = await generateText({
        model: getModel(MODEL),
        system: SYSTEM_PROMPT,
        messages: [{ role: 'user', content: userContent }],
        tools,
        maxSteps: 15,
    });

    const apiCalls = client.callLog.length;
    const errors = client.callLog.filter(c => c.status >= 400).length;
    console.log(`[AGENT] Done. Steps: ${result.steps.length}, API calls: ${apiCalls}, errors: ${errors}`);
    console.log(`[AGENT] Final text: ${result.text?.slice(0, 200)}`);
};
