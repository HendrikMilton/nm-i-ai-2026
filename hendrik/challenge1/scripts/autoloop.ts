#!/usr/bin/env bun
/**
 * Single-shot submit script for Challenge 1.
 * 1. Ensures bun server is running (starts if not)
 * 2. Ensures SSH tunnel is running (starts if not)
 * 3. Checks queue, waits if busy
 * 4. Submits one task
 * 5. Waits for log to appear and complete
 * 6. Prints the full log
 * 7. Exits (so Claude can analyze and re-run)
 */

import { spawn, execSync } from "child_process";
import { readdirSync, readFileSync, existsSync } from "fs";
import { join } from "path";

const ROOT = join(import.meta.dir, "..");
const LOGS_DIR = join(ROOT, "logs");
const ACCESS_TOKEN = process.env.ACCESS_TOKEN!;
const ENDPOINT_URL = "https://tripletex.hycapital.io/solve";
const SUBMIT_URL = "https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions";
const SUBMISSIONS_URL = "https://api.ainm.no/tripletex/my/submissions";

if (!ACCESS_TOKEN) {
  console.error("ERROR: ACCESS_TOKEN env var required");
  process.exit(1);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function latestLog(): string | null {
  if (!existsSync(LOGS_DIR)) return null;
  const files = readdirSync(LOGS_DIR).sort().reverse();
  return files[0] ?? null;
}

async function fetchJson(url: string, opts?: RequestInit) {
  const res = await fetch(url, {
    ...opts,
    headers: {
      "content-type": "application/json",
      cookie: `access_token=${ACCESS_TOKEN}`,
      ...((opts?.headers as Record<string, string>) ?? {}),
    },
  });
  return res.json();
}

// --- Ensure server is running ---
function ensureServer() {
  try {
    const out = execSync("lsof -ti:4001 2>/dev/null", { encoding: "utf-8" }).trim();
    if (out) {
      console.log("✅ Server already running on :4001");
      return;
    }
  } catch {}

  console.log("🚀 Starting bun server with hot reload...");
  spawn("bun", ["--watch", "run", "src/index.ts"], {
    cwd: ROOT,
    env: { ...process.env, MODEL: "claude-opus-4-6", PORT: "4001" },
    stdio: "ignore",
    detached: true,
  }).unref();
}

// --- Ensure SSH tunnel is running ---
function ensureTunnel() {
  try {
    const out = execSync("pgrep -f 'ssh.*-R.*4001.*157.90' 2>/dev/null", { encoding: "utf-8" }).trim();
    if (out) {
      console.log("✅ SSH tunnel already running");
      return;
    }
  } catch {}

  console.log("🔗 Starting SSH reverse tunnel...");
  spawn(
    "ssh",
    [
      "-o", "StrictHostKeyChecking=no",
      "-o", "ServerAliveInterval=30",
      "-o", "ServerAliveCountMax=3",
      "-o", "ExitOnForwardFailure=yes",
      "-N",
      "-R", "0.0.0.0:4001:localhost:4001",
      "root@157.90.171.156",
    ],
    { stdio: "ignore", detached: true }
  ).unref();
}

// --- Wait for queue to clear ---
async function waitQueueClear(): Promise<void> {
  while (true) {
    try {
      const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
      const active = subs.filter(
        (s: any) => s.status === "evaluating" || s.status === "pending" || s.status === "running" || s.status === "queued"
      );
      if (active.length === 0) return;
      console.log(`⏳ ${active.length} submission(s) in progress, waiting 30s...`);
    } catch (e: any) {
      console.log(`⚠️  Error checking queue: ${e.message}, retrying in 30s...`);
    }
    await sleep(30_000);
  }
}

// --- Submit ---
async function submit(): Promise<string | null> {
  try {
    const res = (await fetchJson(SUBMIT_URL, {
      method: "POST",
      body: JSON.stringify({ endpoint_url: ENDPOINT_URL, endpoint_api_key: null }),
    })) as any;
    console.log(`📤 Submitted: ${res.id?.slice(0, 8)} (${res.daily_submissions_used}/${res.daily_submissions_max} today)`);
    return res.id;
  } catch (e: any) {
    console.error(`❌ Submit failed: ${e.message}`);
    return null;
  }
}

// --- Wait for log ---
function waitForNewLog(prevLog: string | null, timeoutMs = 120_000): Promise<string | null> {
  return new Promise((resolve) => {
    const start = Date.now();
    const interval = setInterval(() => {
      const cur = latestLog();
      if (cur && cur !== prevLog) {
        clearInterval(interval);
        resolve(cur);
      } else if (Date.now() - start > timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, 2000);
  });
}

function waitForLogDone(logFile: string, timeoutMs = 300_000): Promise<boolean> {
  return new Promise((resolve) => {
    const path = join(LOGS_DIR, logFile);
    const start = Date.now();
    const interval = setInterval(() => {
      try {
        const content = readFileSync(path, "utf-8");
        if (content.trimEnd().endsWith("---")) {
          clearInterval(interval);
          resolve(true);
        }
      } catch {}
      if (Date.now() - start > timeoutMs) {
        clearInterval(interval);
        resolve(false);
      }
    }, 2000);
  });
}

// --- Main ---
async function main() {
  console.log("═══════════════════════════════════════");
  console.log("  Challenge 1 — Submit & Wait");
  console.log("═══════════════════════════════════════\n");

  ensureServer();
  await sleep(2000);
  ensureTunnel();
  await sleep(2000);

  // Verify connectivity
  try {
    const res = await fetch("http://localhost:4001/");
    if (!res.ok) throw new Error(`status ${res.status}`);
    console.log("✅ Server responding locally");
  } catch (e: any) {
    console.error(`❌ Server not responding: ${e.message}`);
    process.exit(1);
  }

  console.log("\n--- Checking queue ---");
  await waitQueueClear();

  console.log("\n--- Submitting ---");
  const prevLog = latestLog();
  const id = await submit();
  if (!id) {
    console.error("Failed to submit, exiting");
    process.exit(1);
  }

  console.log("\n--- Waiting for task to arrive ---");
  const newLog = await waitForNewLog(prevLog);
  if (!newLog) {
    console.error("⚠️  No log appeared within 2 minutes");
    process.exit(1);
  }

  console.log(`--- Processing: ${newLog} ---`);
  const done = await waitForLogDone(newLog);

  const logPath = join(LOGS_DIR, newLog);
  const content = readFileSync(logPath, "utf-8");

  if (!done) {
    console.log("⚠️  Log didn't complete in time");
  }

  const doneMatch = content.match(/DONE elapsed=(\S+) steps=(\d+) apiCalls=(\d+) errors=(\d+)/);
  if (doneMatch) {
    const [, elapsed, , apiCalls, errors] = doneMatch;
    console.log(`\n⏱  ${elapsed} | ${apiCalls} API calls | ${errors} errors`);
  }

  console.log(`📁 Log: ${logPath}`);

  // Poll for score (platform needs time to evaluate)
  console.log("\nWaiting for score...");
  for (let i = 0; i < 6; i++) {
    await sleep(10_000);
    try {
      const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
      const sub = subs.find((s: any) => s.id === id);
      if (sub?.score_raw !== undefined && sub?.score_raw !== null) {
        const checks = sub.feedback?.checks ?? [];
        const failed = checks.filter((c: string) => c.includes("failed"));
        console.log(`📊 Score: ${sub.score_raw}/${sub.score_max} (normalized: ${sub.normalized_score}) | ${sub.feedback?.comment ?? ""}`);
        if (failed.length > 0) console.log(`   Failed: ${failed.join(", ")}`);
        console.log(`📋 Full feedback: ${JSON.stringify(sub.feedback, null, 2)}`);
        break;
      }
    } catch {}
    if (i === 5) console.log("📊 Score: still pending");
  }

  console.log("\n⏳ Sleeping 30s before exit (rate limit)...");
  await sleep(30_000);
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
