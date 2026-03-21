export class TripletexClient {
    private baseUrl: string;
    private auth: string;
    public callLog: { method: string; path: string; status: number }[] = [];
    public onLog?: (msg: string) => void;

    constructor(baseUrl: string, sessionToken: string) {
        this.baseUrl = baseUrl.replace(/\/$/, '');
        this.auth = 'Basic ' + btoa(`0:${sessionToken}`);
    }

    private async request(method: string, path: string, body?: unknown, params?: Record<string, string>) {
        const url = new URL(`${this.baseUrl}${path}`);
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                url.searchParams.set(k, v);
            }
        }

        const headers: Record<string, string> = {
            Authorization: this.auth,
            'Content-Type': 'application/json',
        };

        const res = await fetch(url.toString(), {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
        });

        const status = res.status;
        this.callLog.push({ method, path, status });
        const qs = url.search ? url.search : '';
        const logLine = `[API] ${method} ${path}${qs} → ${status}${body ? ' body=' + JSON.stringify(body) : ''}`;
        console.log(logLine);
        this.onLog?.(logLine);

        const text = await res.text();
        if (!text) {
            this.onLog?.(`[API] ← (empty)`);
            return { status };
        }

        try {
            const json = JSON.parse(text);
            this.onLog?.(`[API] ← ${text}`);
            if (status >= 400) {
                console.error(`[API] Error: ${text.slice(0, 500)}`);
            }
            return json;
        } catch {
            this.onLog?.(`[API] ← ${text}`);
            return { status, body: text };
        }
    }

    get(path: string, params?: Record<string, string>) {
        return this.request('GET', path, undefined, params);
    }
    post(path: string, body: unknown, params?: Record<string, string>) {
        return this.request('POST', path, body, params);
    }
    put(path: string, body: unknown, params?: Record<string, string>) {
        return this.request('PUT', path, body, params);
    }
    delete(path: string) {
        return this.request('DELETE', path);
    }
}
