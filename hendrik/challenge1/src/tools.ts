import { tool } from 'ai';
import { z } from 'zod';
import { TripletexClient } from './tripletex';

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
        execute: async ({ path, body, params }) => client.post(path, body, params),
    }),

    tripletex_put: tool({
        description: 'Make a PUT request to the Tripletex API to update an existing resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /customer/123'),
            body: z.record(z.unknown()).describe('JSON body with updated fields'),
            params: z.record(z.string()).optional().describe('Query parameters'),
        }),
        execute: async ({ path, body, params }) => client.put(path, body, params),
    }),

    tripletex_delete: tool({
        description: 'Make a DELETE request to the Tripletex API to remove a resource.',
        parameters: z.object({
            path: z.string().describe('API path with ID, e.g. /travelExpense/456'),
        }),
        execute: async ({ path }) => client.delete(path),
    }),
});
