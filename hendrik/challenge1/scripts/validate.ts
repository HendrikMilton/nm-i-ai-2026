import { readFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

const TRIPLETEX_URL = 'https://kkpqfuj-amager.tripletex.dev/v2';
const TOKEN = 'REDACTED_TOKEN';
const AUTH = 'Basic ' + btoa(`0:${TOKEN}`);

interface Check {
    endpoint: string;
    params: Record<string, string>;
    expect: {
        minResults?: number;
        fields?: Record<string, unknown>;
        nested?: Record<string, unknown>;
    };
}

interface ValidateConfig {
    description: string;
    checks: Check[];
    maxApiCalls: number;
    maxErrors: number;
}

const tripletexGet = async (path: string, params: Record<string, string>) => {
    const url = new URL(`${TRIPLETEX_URL}${path}`);
    for (const [k, v] of Object.entries(params)) {
        url.searchParams.set(k, v);
    }
    const res = await fetch(url.toString(), { headers: { Authorization: AUTH } });
    return res.json() as Promise<{ fullResultSize: number; values: Record<string, unknown>[] }>;
};

const fuzzyMatch = (expected: unknown, actual: unknown): boolean => {
    if (expected === actual) {
        return true;
    }
    // Number comparison with tolerance
    if (typeof expected === 'number' && typeof actual === 'number') {
        return Math.abs(expected - actual) < 0.01;
    }
    // String-number comparison (e.g. "2200" vs "2200.0000")
    if (typeof expected === 'number' && typeof actual === 'string') {
        return Math.abs(expected - parseFloat(actual)) < 0.01;
    }
    if (typeof expected === 'string' && typeof actual === 'number') {
        return Math.abs(parseFloat(expected) - actual) < 0.01;
    }
    // Boolean vs string
    if (typeof expected === 'boolean') {
        return String(expected) === String(actual);
    }
    // Case-insensitive string
    if (typeof expected === 'string' && typeof actual === 'string') {
        return expected.toLowerCase() === actual.toLowerCase();
    }
    return false;
};

const getNestedValue = (obj: Record<string, unknown>, path: string): unknown => {
    return path.split('.').reduce((o: unknown, key) => {
        if (o && typeof o === 'object') {
            return (o as Record<string, unknown>)[key];
        }
        return undefined;
    }, obj);
};

const findMatchingResult = (
    values: Record<string, unknown>[],
    fields: Record<string, unknown>,
): Record<string, unknown> | null => {
    // Try to find a result where ALL expected fields match
    for (const v of values) {
        const allMatch = Object.entries(fields).every(([key, expected]) => {
            const actual = getNestedValue(v, key);
            return fuzzyMatch(expected, actual);
        });
        if (allMatch) {
            return v;
        }
    }
    // Fallback: find result with most matches
    let bestMatch: Record<string, unknown> | null = null;
    let bestCount = 0;
    for (const v of values) {
        const matchCount = Object.entries(fields).filter(([key, expected]) => {
            const actual = getNestedValue(v, key);
            return fuzzyMatch(expected, actual);
        }).length;
        if (matchCount > bestCount) {
            bestCount = matchCount;
            bestMatch = v;
        }
    }
    return bestMatch;
};

interface LogEntry {
    elapsed: string;
    steps: number;
    apiCalls: number;
    errors: number;
}

const parseLogFile = (model: string): LogEntry[] => {
    const logPath = join('src', `logs-${model}.log`);
    if (!existsSync(logPath)) {
        return [];
    }
    const lines = readFileSync(logPath, 'utf-8').split('\n');
    return lines
        .filter(l => l.includes('[AGENT] DONE'))
        .map(l => {
            const elapsed = l.match(/elapsed=(\S+)s/)?.[1] ?? '?';
            const steps = parseInt(l.match(/steps=(\d+)/)?.[1] ?? '0');
            const apiCalls = parseInt(l.match(/apiCalls=(\d+)/)?.[1] ?? '0');
            const errors = parseInt(l.match(/errors=(\d+)/)?.[1] ?? '0');
            return { elapsed, steps, apiCalls, errors };
        });
};

const main = async () => {
    const model = process.argv[2] ?? 'claude-opus-4-6';
    const logEntries = parseLogFile(model);

    console.log('==========================================');
    console.log(`VALIDATION — model: ${model}`);
    console.log('==========================================');

    let totalFieldChecks = 0;
    let passedFieldChecks = 0;
    let failedFieldChecks = 0;
    let efficiencyPass = 0;
    let efficiencyFail = 0;
    let taskIndex = 0;

    for (const dir of ['easy', 'medium', 'hard']) {
        const dirPath = join('test-tasks', dir);
        if (!existsSync(dirPath)) {
            continue;
        }
        const files = readdirSync(dirPath).filter(f => f.endsWith('.validate.json')).sort();

        for (const file of files) {
            const config: ValidateConfig = JSON.parse(readFileSync(join(dirPath, file), 'utf-8'));
            const taskName = file.replace('.validate.json', '');
            const log = logEntries[taskIndex];
            taskIndex++;

            console.log(`\n--- [${dir}] ${taskName}: ${config.description} ---`);

            // Efficiency checks
            if (log) {
                if (log.apiCalls <= config.maxApiCalls) {
                    console.log(`  ✓ API calls: ${log.apiCalls} <= ${config.maxApiCalls}`);
                    efficiencyPass++;
                } else {
                    console.log(`  ✗ API calls: ${log.apiCalls} > ${config.maxApiCalls}`);
                    efficiencyFail++;
                }
                if (log.errors <= config.maxErrors) {
                    console.log(`  ✓ Errors: ${log.errors} <= ${config.maxErrors}`);
                    efficiencyPass++;
                } else {
                    console.log(`  ✗ Errors: ${log.errors} > ${config.maxErrors}`);
                    efficiencyFail++;
                }
                console.log(`  ⏱ Time: ${log.elapsed}s`);
            } else {
                console.log('  ⚠ No log entry found');
            }

            // Field checks
            for (const check of config.checks) {
                const data = await tripletexGet(check.endpoint, check.params);
                const minResults = check.expect.minResults ?? 1;

                totalFieldChecks++;
                if (data.fullResultSize >= minResults) {
                    console.log(`  ✓ Found ${data.fullResultSize} result(s) at ${check.endpoint}`);
                    passedFieldChecks++;
                } else {
                    console.log(`  ✗ Expected >= ${minResults} at ${check.endpoint}, got ${data.fullResultSize}`);
                    failedFieldChecks++;
                    continue;
                }

                // Check fields
                const fieldsToCheck = { ...check.expect.fields, ...check.expect.nested };
                if (fieldsToCheck && Object.keys(fieldsToCheck).length > 0) {
                    const match = findMatchingResult(data.values, fieldsToCheck);
                    if (!match) {
                        console.log(`  ✗ No result matches expected fields`);
                        for (const [key, expected] of Object.entries(fieldsToCheck)) {
                            totalFieldChecks++;
                            failedFieldChecks++;
                            console.log(`    ✗ ${key}: expected '${expected}', no match found`);
                        }
                        continue;
                    }

                    for (const [key, expected] of Object.entries(fieldsToCheck)) {
                        const actual = getNestedValue(match, key);
                        totalFieldChecks++;
                        if (fuzzyMatch(expected, actual)) {
                            console.log(`  ✓ ${key} = ${actual}`);
                            passedFieldChecks++;
                        } else {
                            console.log(`  ✗ ${key}: expected '${expected}', got '${actual}'`);
                            failedFieldChecks++;
                        }
                    }
                }
            }
        }
    }

    console.log('\n==========================================');
    console.log('VALIDATION SUMMARY');
    console.log('==========================================');
    console.log(`Field checks:      ${passedFieldChecks}/${totalFieldChecks} passed`);
    console.log(`Efficiency checks: ${efficiencyPass} passed, ${efficiencyFail} failed`);
    console.log(`Failed:            ${failedFieldChecks} field + ${efficiencyFail} efficiency`);
    console.log('==========================================');
};

main().catch(console.error);
