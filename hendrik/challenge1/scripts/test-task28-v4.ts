#!/usr/bin/env bun
/**
 * Task 28 test v4: Simulate what the EVALUATOR might do.
 * Test every possible way the evaluator could query and verify projects.
 */
const BASE_URL = "https://kkpqfuj-amager.tripletex.dev/v2";
const SESSION_TOKEN = "REDACTED_TOKEN";
const AUTH = "Basic " + btoa(`0:${SESSION_TOKEN}`);

async function api(method: string, path: string, body?: unknown, params?: Record<string, string>) {
  const url = new URL(`${BASE_URL}${path}`);
  if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url.toString(), {
    method,
    headers: { Authorization: AUTH, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json; try { json = JSON.parse(text); } catch { json = { raw: text }; }
  if (res.status >= 400) console.log(`  ERROR ${method} ${path} → ${res.status}:`, JSON.stringify(json).slice(0, 300));
  return { status: res.status, data: json };
}

const TS = Date.now();

async function main() {
  console.log("=== TASK 28 EVALUATOR SIMULATION ===\n");

  const emp = await api("GET", "/employee", undefined, { fields: "id", count: "1" });
  const empId = emp.data.values?.[0]?.id;

  // Create 3 projects with 2 DIFFERENT approaches
  // Approach A: Current approach (PROJECT_GENERAL_ACTIVITY, gpapOnly=false)
  // Approach B: New approach (PROJECT_SPECIFIC_ACTIVITY, gpapOnly=true, sequential)

  console.log("=== Creating Approach A projects (current buggy approach) ===");
  const namesA = [`ApA Bilgodtgjørelse ${TS}`, `ApA Motordrevet ${TS}`, `ApA Lønn ${TS}`];
  const projectsA: number[] = [];
  const activitiesA: number[] = [];

  // Parallel project + activity creation (current approach)
  const projPromisesA = namesA.map(n => api("POST", "/project", {
    name: n, projectManager: { id: empId }, startDate: "2026-03-22", isInternal: true
  }));
  const actPromisesA = namesA.map(n => api("POST", "/activity", {
    name: n, activityType: "PROJECT_GENERAL_ACTIVITY", isChargeable: false
  }));
  const projResultsA = await Promise.all(projPromisesA);
  const actResultsA = await Promise.all(actPromisesA);
  for (const r of projResultsA) projectsA.push(r.data.value?.id);
  for (const r of actResultsA) activitiesA.push(r.data.value?.id);

  // Sequential linking
  for (let i = 0; i < 3; i++) {
    await api("POST", "/project/projectActivity", {
      project: { id: projectsA[i] }, activity: { id: activitiesA[i] }, startDate: "2026-03-22"
    });
  }
  console.log("  Created A projects:", projectsA);

  console.log("\n=== Creating Approach B projects (new approach) ===");
  const namesB = [`ApB Bilgodtgjørelse ${TS}`, `ApB Motordrevet ${TS}`, `ApB Lønn ${TS}`];
  const projectsB: number[] = [];

  // Sequential project + specific activity creation
  for (const n of namesB) {
    const proj = await api("POST", "/project", {
      name: n, projectManager: { id: empId }, startDate: "2026-03-22",
      isInternal: true, generalProjectActivitiesPerProjectOnly: true
    });
    const pid = proj.data.value?.id;
    projectsB.push(pid);

    // Create project-specific activity inline
    await api("POST", "/project/projectActivity", {
      project: { id: pid },
      activity: { name: n, activityType: "PROJECT_SPECIFIC_ACTIVITY" },
      startDate: "2026-03-22"
    });
  }
  console.log("  Created B projects:", projectsB);

  // Now simulate EVALUATOR queries
  console.log("\n\n========================================");
  console.log("=== EVALUATOR SIMULATION QUERIES ===");
  console.log("========================================\n");

  // Method 1: GET /project?name=X (exact name search)
  console.log("--- Method 1: Search by exact name ---");
  for (const n of namesA) {
    const r = await api("GET", "/project", undefined, { name: n, fields: "id,name,isInternal,projectActivities(id,activity(id,name))" });
    const found = r.data.values?.length || 0;
    const acts = r.data.values?.[0]?.projectActivities?.length || 0;
    console.log(`  A "${n}": found=${found} activities=${acts}`);
  }
  for (const n of namesB) {
    const r = await api("GET", "/project", undefined, { name: n, fields: "id,name,isInternal,projectActivities(id,activity(id,name))" });
    const found = r.data.values?.length || 0;
    const acts = r.data.values?.[0]?.projectActivities?.length || 0;
    console.log(`  B "${n}": found=${found} activities=${acts}`);
  }

  // Method 2: GET all internal projects, filter by name client-side
  console.log("\n--- Method 2: GET all internal projects with activities ---");
  const allInternal = await api("GET", "/project", undefined, {
    isInternal: "true", count: "200",
    fields: "id,name,number,isInternal,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
  });
  console.log(`  Total internal projects: ${allInternal.data.fullResultSize}`);

  // Show our A projects
  console.log("\n  Approach A projects:");
  for (const pid of projectsA) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    if (p) {
      console.log(`    id=${p.id} num=${p.number} name="${p.name}" gpapOnly=${p.generalProjectActivitiesPerProjectOnly}`);
      for (const pa of p.projectActivities || []) {
        console.log(`      activity: name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
      }
    }
  }

  // Show our B projects
  console.log("\n  Approach B projects:");
  for (const pid of projectsB) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    if (p) {
      console.log(`    id=${p.id} num=${p.number} name="${p.name}" gpapOnly=${p.generalProjectActivitiesPerProjectOnly}`);
      for (const pa of p.projectActivities || []) {
        console.log(`      activity: name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
      }
    }
  }

  // Method 3: Check if activity name matches project name
  console.log("\n--- Method 3: Activity name == Project name? ---");
  for (const pid of projectsA) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    if (p) {
      const match = p.projectActivities?.some((pa: any) => pa.activity?.name === p.name);
      console.log(`  A "${p.name}": activity name matches project name = ${match}`);
    }
  }
  for (const pid of projectsB) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    if (p) {
      const match = p.projectActivities?.some((pa: any) => pa.activity?.name === p.name);
      console.log(`  B "${p.name}": activity name matches project name = ${match}`);
    }
  }

  // Method 4: Check project numbers (are they unique/sequential?)
  console.log("\n--- Method 4: Project numbers ---");
  for (const pid of projectsA) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    console.log(`  A id=${p?.id} number="${p?.number}" name="${p?.name}"`);
  }
  for (const pid of projectsB) {
    const p = (allInternal.data.values || []).find((v: any) => v.id === pid);
    console.log(`  B id=${p?.id} number="${p?.number}" name="${p?.name}"`);
  }

  // Method 5: Search by activity name
  console.log("\n--- Method 5: Search activities by name ---");
  for (const n of namesA) {
    const r = await api("GET", "/activity", undefined, { name: n, fields: "id,name,activityType,isGeneral" });
    const v = r.data.values?.[0];
    console.log(`  A "${n}": type=${v?.activityType} isGeneral=${v?.isGeneral}`);
  }
  for (const n of namesB) {
    const r = await api("GET", "/activity", undefined, { name: n, fields: "id,name,activityType,isGeneral" });
    const v = r.data.values?.[0];
    console.log(`  B "${n}": found=${r.data.values?.length || 0} type=${v?.activityType} isGeneral=${v?.isGeneral}`);
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
