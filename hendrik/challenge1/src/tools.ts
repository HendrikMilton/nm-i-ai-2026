import { tool } from 'ai';
import { z } from 'zod';
import { TripletexClient } from './tripletex';

export const createTools = (client: TripletexClient, files?: { filename: string; content_base64: string; mime_type: string }[]) => ({
    tripletex_get: tool({
        description: 'Make a GET request to the Tripletex API. Use params for query parameters like fields, count, from, name, etc.',
        parameters: z.object({
            path: z.string().describe('API path, e.g. /employee, /customer, /product'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, params }) => client.get(path, params),
    }),

    tripletex_post: tool({
        description: 'Make a POST request to the Tripletex API to create a resource.',
        parameters: z.object({
            path: z.string().describe('API path, e.g. /employee, /customer, /order/orderline'),
            body: z.unknown().describe('JSON body to send (object or array)'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, body, params }) => client.post(path, body as any, params),
    }),

    tripletex_put: tool({
        description: 'Make a PUT request to the Tripletex API to update an existing resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /customer/123'),
            body: z.unknown().describe('JSON body with updated fields (object or array)'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, body, params }) => client.put(path, body as any, params),
    }),

    tripletex_delete: tool({
        description: 'Make a DELETE request to the Tripletex API to remove a resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /travelExpense/456'),
        }),
        execute: async ({ path }) => client.delete(path),
    }),

    tripletex_upload_attachment: tool({
        description: 'Upload a PDF file attachment to a voucher. Uses the first file from the request.',
        parameters: z.object({
            voucherId: z.number().describe('Voucher ID to attach the file to'),
        }),
        execute: async ({ voucherId }) => {
            if (!files?.length) return { error: 'No files available to upload' };
            const file = files[0];
            const buffer = Buffer.from(file.content_base64, 'base64');
            return client.uploadFile(`/ledger/voucher/${voucherId}/attachment`, buffer, file.filename);
        },
    }),

    calculate: tool({
        description: 'Evaluate a mathematical expression. Use for any arithmetic: sums, divisions, percentages, rounding. Returns the numeric result. Examples: "288400 / 3", "Math.round(288400 / 3 * 100) / 100", "[1,2,3].reduce((a,b) => a+b, 0)"',
        parameters: z.object({
            expression: z.string().describe('JavaScript math expression to evaluate'),
        }),
        execute: async ({ expression }) => {
            try {
                const raw = new Function(expression.includes('return') ? expression : `return (${expression})`)();
                const result = typeof raw === 'number' ? Math.round(raw * 100) / 100 : raw;
                return { result };
            } catch (e: any) {
                return { error: e.message };
            }
        },
    }),
});
