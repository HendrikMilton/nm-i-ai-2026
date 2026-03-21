#!/usr/bin/env bun
/**
 * Minimal auto-loop: submit → wait for score → repeat forever.
 * Usage: ACCESS_TOKEN=xxx bun scripts/autoloop-minimal.ts
 */

import { readdirSync, readFileSync, existsSync, appendFileSync } from "fs";
import { join } from "path";
import { execSync } from "child_process";

const ROOT = join(import.meta.dir, "..");
const LOGS_DIR = join(ROOT, "logs");
const ACCESS_TOKEN = process.env.ACCESS_TOKEN!;
const ENDPOINT_URL = process.env.ENDPOINT_URL ?? "https://challenge1.hycapital.io/solve";
const SUBMIT_URL = "https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions";
const LEADERBOARD_URL = "https://api.ainm.no/tripletex/leaderboard";
const SUBMISSIONS_URL = "https://api.ainm.no/tripletex/my/submissions";
const MAX_DAILY_SUBMISSIONS = Number(process.env.MAX_DAILY_SUBMISSIONS ?? 150);

if (!ACCESS_TOKEN) {
  console.error("ERROR: ACCESS_TOKEN env var required");
  process.exit(1);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let round = 0;

function ts() {
  return new Date().toISOString().slice(11, 19);
}

function latestLog(): string | null {
  if (!existsSync(LOGS_DIR)) return null;
  const files = readdirSync(LOGS_DIR).filter(f => f.endsWith('.log')).sort().reverse();
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

async function waitQueueClear(): Promise<void> {
  while (true) {
    try {
      const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
      const active = subs.filter(
        (s: any) => ["evaluating", "pending", "running", "queued"].includes(s.status)
      );
      if (active.length === 0) return;
      console.log(`  [${ts()}] ${active.length} submission(s) in progress, waiting 15s...`);
    } catch (e: any) {
      console.log(`  [${ts()}] queue check error: ${e.message}, retrying...`);
    }
    await sleep(15_000);
  }
}

async function submit(): Promise<{ id: string | null; dailyUsed: number }> {
  try {
    const res = (await fetchJson(SUBMIT_URL, {
      method: "POST",
      body: JSON.stringify({ endpoint_url: ENDPOINT_URL, endpoint_api_key: null }),
    })) as any;
    const used = res.daily_submissions_used ?? 0;
    console.log(`  [${ts()}] submitted: ${res.id?.slice(0, 8)} (${used}/${res.daily_submissions_max} today, limit=${MAX_DAILY_SUBMISSIONS})`);
    return { id: res.id, dailyUsed: used };
  } catch (e: any) {
    console.error(`  [${ts()}] submit failed: ${e.message}`);
    return { id: null, dailyUsed: 0 };
  }
}

async function waitForScore(submissionId: string): Promise<any> {
  for (let i = 0; i < 60; i++) {
    await sleep(10_000);
    try {
      const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
      const sub = subs.find((s: any) => s.id === submissionId);
      if (sub?.score_raw !== undefined && sub?.score_raw !== null) {
        return sub;
      }
      if (sub?.status === "failed" || sub?.status === "error") {
        return sub;
      }
    } catch {}
  }
  return null;
}

async function getLeaderboard(): Promise<string> {
  try {
    const lb = (await fetchJson(LEADERBOARD_URL)) as any[];
    const us = lb.find((t: any) => t.team_slug === "agentic-avengers");
    const top = lb[0];
    return `rank=${us?.rank} score=${us?.total_score} tasks=${us?.tasks_touched}/30 | #1: ${top?.team_slug} ${top?.total_score}`;
  } catch {
    return "leaderboard fetch failed";
  }
}

// --- Main loop ---
async function main() {
  console.log("=== autoloop-minimal: submit → score → repeat ===");
  console.log(`endpoint: ${ENDPOINT_URL}\n`);

  // Verify server is up
  try {
    const res = await fetch("http://localhost:4001/");
    if (!res.ok) throw new Error(`status ${res.status}`);
    console.log(`[${ts()}] server OK\n`);
  } catch (e: any) {
    console.error(`server not responding on :4001 — ${e.message}`);
    process.exit(1);
  }

  while (true) {
    round++;
    console.log(`\n--- round ${round} ---`);

    // 1. Wait for queue
    await waitQueueClear();

    // 2. Submit
    const { id, dailyUsed } = await submit();
    if (!id) {
      console.log(`  [${ts()}] submit failed, retrying in 30s...`);
      await sleep(30_000);
      continue;
    }
    if (dailyUsed >= MAX_DAILY_SUBMISSIONS) {
      console.log(`  [${ts()}] daily limit reached (${dailyUsed}/${MAX_DAILY_SUBMISSIONS}), stopping.`);
      break;
    }

    // 3. Wait for score
    console.log(`  [${ts()}] waiting for score...`);
    const sub = await waitForScore(id);

    if (!sub) {
      console.log(`  [${ts()}] timed out waiting for score`);
    } else if (sub.status === "failed" || sub.status === "error") {
      console.log(`  [${ts()}] submission ${sub.status}: ${sub.feedback?.comment ?? "no details"}`);
    } else {
      const checks = sub.feedback?.checks ?? [];
      const passed = checks.filter((c: string) => c.includes("passed")).length;
      const total = checks.length;
      console.log(`  [${ts()}] score: ${sub.score_raw}/${sub.score_max} (${passed}/${total} checks) | ${sub.feedback?.comment ?? ""}`);

      // Append to log file
      const curLog = latestLog();
      if (curLog) {
        const logPath = join(LOGS_DIR, curLog);
        appendFileSync(logPath, `\n[SCORING] ${JSON.stringify(sub, null, 2)}\n`);
      }
    }

    // 4. Leaderboard
    const lb = await getLeaderboard();
    console.log(`  [${ts()}] ${lb}`);

    // 5. Git commit
    try {
      const repoRoot = join(ROOT, "..", "..");
      execSync("git add -A", { cwd: repoRoot, stdio: "pipe" });
      const hasChanges = execSync("git diff --cached --quiet || echo changes", { cwd: repoRoot, encoding: "utf-8" }).trim();
      if (hasChanges) {
        execSync(`git commit -m "auto submit round ${round}"`, { cwd: repoRoot, stdio: "pipe" });
        execSync("git pull --rebase && git push", { cwd: repoRoot, stdio: "pipe", timeout: 30_000 });
        console.log(`  [${ts()}] git: committed + pushed`);
      }
    } catch (e: any) {
      console.log(`  [${ts()}] git: ${e.message?.slice(0, 80)}`);
    }

    // Brief pause before next round
    await sleep(5_000);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
