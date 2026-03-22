#!/usr/bin/env bun
/**
 * Parallel auto-loop: keeps 3 submissions running at all times.
 * Tracks in-flight count locally (doesn't trust API latency).
 * Pushes logs after each completed submission.
 * Usage: ACCESS_TOKEN=xxx bun scripts/autoloop-minimal-v3.ts
 */

import { readdirSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import { execSync } from "child_process";

const ROOT = join(import.meta.dir, "..");
const LOGS_DIR = join(ROOT, "logs");
const ACCESS_TOKEN = process.env.ACCESS_TOKEN!;
const ENDPOINT_URL = process.env.ENDPOINT_URL ?? "https://challenge1.hycapital.io/solve";
const SUBMIT_URL = "https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions";
const SUBMISSIONS_URL = "https://api.ainm.no/tripletex/my/submissions";
const MAX_CONCURRENT = 1;

if (!ACCESS_TOKEN) {
  console.error("ERROR: ACCESS_TOKEN env var required");
  process.exit(1);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let totalSubmitted = 0;
let inFlight = 0;

function ts() {
  return new Date().toISOString().slice(11, 19);
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

async function submit(): Promise<string | null> {
  try {
    const res = (await fetchJson(SUBMIT_URL, {
      method: "POST",
      body: JSON.stringify({ endpoint_url: ENDPOINT_URL, endpoint_api_key: null }),
    })) as any;
    if (!res.id) {
      console.error(`  [${ts()}] submit returned no id:`, JSON.stringify(res).slice(0, 200));
      return null;
    }
    const used = res.daily_submissions_used ?? 0;
    const max = res.daily_submissions_max ?? 300;
    totalSubmitted++;
    console.log(`  [${ts()}] submitted #${totalSubmitted}: ${res.id.slice(0, 8)} (${used}/${max} today)`);
    if (used >= Math.floor(max / 2)) {
      console.log(`  [${ts()}] reached half daily limit, stopping.`);
      process.exit(0);
    }
    return res.id;
  } catch (e: any) {
    console.error(`  [${ts()}] submit failed: ${e.message}`);
    return null;
  }
}

async function waitForCompletion(submissionId: string): Promise<void> {
  for (let i = 0; i < 120; i++) {  // max 10 min (120 * 5s)
    await sleep(5_000);
    try {
      const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
      if (!Array.isArray(subs)) continue;
      const sub = subs.find((s: any) => s.id === submissionId);
      if (!sub) continue;
      if (sub.status === "completed" || sub.status === "failed" || sub.status === "error") {
        const checks = sub.feedback?.checks ?? [];
        const passed = checks.filter((c: string) => c.includes("passed")).length;
        const total = checks.length;
        console.log(`  [${ts()}] ${submissionId.slice(0, 8)} done: ${sub.score_raw ?? "?"}/${sub.score_max ?? "?"} (${passed}/${total} checks) ${sub.status}`);
        return;
      }
    } catch {}
  }
  console.log(`  [${ts()}] ${submissionId.slice(0, 8)} timed out`);
}

function gitPush() {
  try {
    const repoRoot = join(ROOT, "..", "..");
    execSync("git add -A", { cwd: repoRoot, stdio: "pipe" });
    const hasChanges = execSync("git diff --cached --quiet || echo changes", { cwd: repoRoot, encoding: "utf-8" }).trim();
    if (hasChanges) {
      execSync(`git commit -m "auto submit round ${totalSubmitted}"`, { cwd: repoRoot, stdio: "pipe" });
      execSync("git pull --rebase && git push", { cwd: repoRoot, stdio: "pipe", timeout: 30_000 });
      console.log(`  [${ts()}] git: committed + pushed`);
    }
  } catch (e: any) {
    console.log(`  [${ts()}] git: ${e.message?.slice(0, 80)}`);
  }
}

async function runSubmission(): Promise<void> {
  inFlight++;
  try {
    const id = await submit();
    if (!id) {
      await sleep(10_000);
      return;
    }
    await waitForCompletion(id);
    gitPush();
  } finally {
    inFlight--;
  }
}

async function main() {
  console.log(`=== autoloop-v3: keep ${MAX_CONCURRENT} submissions running ===`);
  console.log(`endpoint: ${ENDPOINT_URL}\n`);

  while (true) {
    const slotsOpen = MAX_CONCURRENT - inFlight;
    if (slotsOpen > 0) {
      console.log(`[${ts()}] ${inFlight} in-flight, launching ${slotsOpen}...`);
      for (let i = 0; i < slotsOpen; i++) {
        // Fire and forget — runs concurrently
        runSubmission().catch((e) => console.error(`  [${ts()}] submission error:`, e.message));
        // Small stagger between launches
        await sleep(2_000);
      }
    }
    // Check for open slots every 10s
    await sleep(10_000);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
