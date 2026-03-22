#!/usr/bin/env bun
/**
 * Fast auto-loop: submit → poll log for completion → submit again immediately.
 * Does NOT wait for scoring — just fires submissions as fast as the agent completes them.
 * Usage: ACCESS_TOKEN=xxx bun scripts/autoloop-minimal-v2.ts
 */

import { readdirSync, existsSync, readFileSync } from "fs";
import { join } from "path";

const ROOT = join(import.meta.dir, "..");
const LOGS_DIR = join(ROOT, "logs");
const ACCESS_TOKEN = process.env.ACCESS_TOKEN!;
const ENDPOINT_URL = process.env.ENDPOINT_URL ?? "https://challenge1.hycapital.io/solve";
const SUBMIT_URL = "https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions";
const SUBMISSIONS_URL = "https://api.ainm.no/tripletex/my/submissions";

if (!ACCESS_TOKEN) {
  console.error("ERROR: ACCESS_TOKEN env var required");
  process.exit(1);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let round = 0;

function ts() {
  return new Date().toISOString().slice(11, 19);
}

function getLogFiles(): string[] {
  if (!existsSync(LOGS_DIR)) return [];
  return readdirSync(LOGS_DIR).filter(f => f.endsWith('.log')).sort();
}

function logIsDone(filename: string): boolean {
  try {
    const content = readFileSync(join(LOGS_DIR, filename), "utf-8");
    return content.includes("[AGENT] DONE");
  } catch {
    return false;
  }
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

async function hasActiveSubmission(): Promise<boolean> {
  try {
    const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
    return subs.some((s: any) =>
      ["evaluating", "pending", "running", "queued"].includes(s.status)
    );
  } catch {
    return false;
  }
}

async function submit(): Promise<string | null> {
  try {
    const res = (await fetchJson(SUBMIT_URL, {
      method: "POST",
      body: JSON.stringify({ endpoint_url: ENDPOINT_URL, endpoint_api_key: null }),
    })) as any;
    const used = res.daily_submissions_used ?? 0;
    const max = res.daily_submissions_max ?? 300;
    console.log(`  [${ts()}] submitted: ${res.id?.slice(0, 8)} (${used}/${max} today)`);
    if (used >= Math.floor(max / 2)) {
      console.log(`  [${ts()}] reached half daily limit, stopping.`);
      process.exit(0);
    }
    return res.id ?? null;
  } catch (e: any) {
    console.error(`  [${ts()}] submit failed: ${e.message}`);
    return null;
  }
}

async function main() {
  console.log("=== autoloop-minimal-v2: submit → poll log → repeat (no score wait) ===");
  console.log(`endpoint: ${ENDPOINT_URL}\n`);

  while (true) {
    round++;
    console.log(`\n--- round ${round} ---`);

    // Wait if there's already an active submission
    while (await hasActiveSubmission()) {
      console.log(`  [${ts()}] active submission exists, waiting 5s...`);
      await sleep(5_000);
    }

    // Record logs before submission
    const logsBefore = new Set(getLogFiles());

    // Submit
    const id = await submit();
    if (!id) {
      console.log(`  [${ts()}] submit failed, retrying in 10s...`);
      await sleep(10_000);
      continue;
    }

    // Poll for new log file to appear and finish
    console.log(`  [${ts()}] waiting for agent to complete...`);
    let found = false;
    for (let i = 0; i < 120; i++) {  // max 4 min (120 * 2s)
      await sleep(2_000);
      const logsNow = getLogFiles();
      const newLogs = logsNow.filter(f => !logsBefore.has(f));

      if (newLogs.length > 0) {
        const latest = newLogs[newLogs.length - 1];
        if (logIsDone(latest)) {
          // Read first line for task info
          const firstLine = readFileSync(join(LOGS_DIR, latest), "utf-8").split("\n")[0];
          const promptMatch = firstLine.match(/prompt="(.{0,60})/);
          console.log(`  [${ts()}] agent done: ${latest}`);
          if (promptMatch) console.log(`  [${ts()}] task: ${promptMatch[1]}...`);
          found = true;
          break;
        }
      }
    }

    if (!found) {
      console.log(`  [${ts()}] timed out waiting for agent completion`);
    }

    // Brief pause then go again
    await sleep(1_000);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
