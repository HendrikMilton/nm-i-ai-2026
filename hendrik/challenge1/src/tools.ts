import { tool } from 'ai';
import { z } from 'zod';
import { TripletexClient } from './tripletex';
import { validatePost, validatePut } from './validators';

export const createTools = (client: TripletexClient) => ({
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
            body: z.record(z.unknown()).describe('JSON body to send'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, body, params }) => {
            const err = validatePost(path, body);
            if (err) return { validation_error: err, hint: "Fix the body and retry." };
            return client.post(path, body, params);
        },
    }),

    tripletex_put: tool({
        description: 'Make a PUT request to the Tripletex API to update an existing resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /customer/123'),
            body: z.record(z.unknown()).describe('JSON body with updated fields'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, body, params }) => {
            const err = validatePut(path, body);
            if (err) return { validation_error: err, hint: "Fix the body and retry." };
            return client.put(path, body, params);
        },
    }),

    tripletex_delete: tool({
        description: 'Make a DELETE request to the Tripletex API to remove a resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /travelExpense/456'),
        }),
        execute: async ({ path }) => client.delete(path),
    }),

    calculate: tool({
        description: 'Evaluate a mathematical expression. Use for any arithmetic: sums, divisions, percentages, rounding. Returns the numeric result. Examples: "288400 / 3", "Math.round(288400 / 3 * 100) / 100", "[1,2,3].reduce((a,b) => a+b, 0)"',
        parameters: z.object({
            expression: z.string().describe('JavaScript math expression to evaluate'),
        }),
        execute: async ({ expression }) => {
            try {
                const result = new Function(`"use strict"; return (${expression})`)();
                return { result };
            } catch (e: any) {
                return { error: e.message };
            }
        },
    }),
});
