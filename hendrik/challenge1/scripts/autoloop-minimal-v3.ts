#!/usr/bin/env bun
/**
 * Parallel auto-loop: keeps 3 submissions running at all times.
 * Submits immediately when a slot opens. Does not wait for scoring.
 * Usage: ACCESS_TOKEN=xxx bun scripts/autoloop-minimal-v3.ts
 */

import { readdirSync, existsSync, readFileSync } from "fs";
import { join } from "path";

const ROOT = join(import.meta.dir, "..");
const LOGS_DIR = join(ROOT, "logs");
const ACCESS_TOKEN = process.env.ACCESS_TOKEN!;
const ENDPOINT_URL = process.env.ENDPOINT_URL ?? "https://challenge1.hycapital.io/solve";
const SUBMIT_URL = "https://api.ainm.no/tasks/cccccccc-cccc-cccc-cccc-cccccccccccc/submissions";
const SUBMISSIONS_URL = "https://api.ainm.no/tripletex/my/submissions";
const MAX_CONCURRENT = 3;

if (!ACCESS_TOKEN) {
  console.error("ERROR: ACCESS_TOKEN env var required");
  process.exit(1);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let totalSubmitted = 0;

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

async function getActiveCount(): Promise<{ active: number; used: number; max: number }> {
  try {
    const subs = (await fetchJson(SUBMISSIONS_URL)) as any[];
    const active = subs.filter((s: any) =>
      ["evaluating", "pending", "running", "queued"].includes(s.status)
    ).length;
    // Estimate daily usage from total completed today
    const today = new Date().toISOString().slice(0, 10);
    const todayCount = subs.filter((s: any) => s.queued_at?.startsWith(today)).length;
    return { active, used: todayCount, max: 300 };
  } catch (e: any) {
    console.log(`  [${ts()}] queue check error: ${e.message}`);
    return { active: 0, used: 0, max: 300 };
  }
}

async function submit(): Promise<boolean> {
  try {
    const res = (await fetchJson(SUBMIT_URL, {
      method: "POST",
      body: JSON.stringify({ endpoint_url: ENDPOINT_URL, endpoint_api_key: null }),
    })) as any;
    const used = res.daily_submissions_used ?? 0;
    const max = res.daily_submissions_max ?? 300;
    totalSubmitted++;
    console.log(`  [${ts()}] submitted #${totalSubmitted}: ${res.id?.slice(0, 8)} (${used}/${max} today)`);
    if (used >= Math.floor(max / 2)) {
      console.log(`  [${ts()}] reached half daily limit, stopping.`);
      process.exit(0);
    }
    return true;
  } catch (e: any) {
    console.error(`  [${ts()}] submit failed: ${e.message}`);
    return false;
  }
}

async function main() {
  console.log(`=== autoloop-v3: keep ${MAX_CONCURRENT} submissions running ===`);
  console.log(`endpoint: ${ENDPOINT_URL}\n`);

  while (true) {
    const { active, used } = await getActiveCount();
    const slotsOpen = MAX_CONCURRENT - active;

    if (slotsOpen > 0) {
      console.log(`[${ts()}] ${active} active, ${slotsOpen} slots open — submitting...`);
      // Submit to fill all open slots
      for (let i = 0; i < slotsOpen; i++) {
        const ok = await submit();
        if (!ok) {
          await sleep(5_000);
          break;
        }
        // Brief pause between submissions to avoid rate limiting
        if (i < slotsOpen - 1) await sleep(1_000);
      }
    }

    // Poll every 5s to check for open slots
    await sleep(5_000);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
