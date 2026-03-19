const BASE_URL = 'http://localhost:3003';

export class HttpError<T = unknown> {
    constructor(public status: number, public body: T) {}
}

const createHttp = () => {
    const makeRequest = async <T>(path: string, method: string, body?: unknown): Promise<T> => {
        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
        };

        const response = await fetch(`${BASE_URL}${path}`, {
            method,
            headers,
            ...(body !== undefined && { body: JSON.stringify(body) }),
        });

        let responseBody: unknown;
        try {
            responseBody = await response.json();
        } catch { /* empty response */ }

        if (!response.ok) {
            throw new HttpError(response.status, responseBody);
        }

        return responseBody as T;
    };

    return {
        get: <T>(path: string) => makeRequest<T>(path, 'GET'),
        post: <T>(path: string, body?: unknown) => makeRequest<T>(path, 'POST', body),
    };
};

export const http = createHttp();
