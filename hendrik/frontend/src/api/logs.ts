import { http } from './http';

export interface LogEntry {
    ts: number;
    elapsed: number;
    request: Record<string, unknown>;
    response: Record<string, unknown>;
    challenge: number;
    index: number;
}

export interface LogsResponse {
    logs: LogEntry[];
    total: number;
    page: number;
    pageSize: number;
}

export async function fetchLogs(params: {
    challenge?: number;
    page?: number;
    pageSize?: number;
}): Promise<LogsResponse> {
    const query = new URLSearchParams();
    if (params.challenge) query.set('challenge', String(params.challenge));
    if (params.page) query.set('page', String(params.page));
    if (params.pageSize) query.set('pageSize', String(params.pageSize));
    return http.get<LogsResponse>(`/logs?${query}`);
}

export async function fetchLogEntry(challenge: number, index: number): Promise<LogEntry> {
    return http.get<LogEntry>(`/logs/${challenge}/${index}`);
}
