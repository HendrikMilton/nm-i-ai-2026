#!/usr/bin/env bun
/**
 * Task 28 deep test v2: Test PROJECT_SPECIFIC activity creation
 * and inline project creation approaches.
 *
 * KEY FINDING from v1: PROJECT_SPECIFIC_ACTIVITY must be created via
 * POST /project/projectActivity, NOT POST /activity.
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
  if (res.status >= 400) console.log(`  ERROR ${method} ${path} → ${res.status}:`, JSON.stringify(json).slice(0, 500));
  return { status: res.status, data: json };
}

async function main() {
  console.log("=== TASK 28 DEEP TEST V2 ===\n");

  const emp = await api("GET", "/employee", undefined, { fields: "id", count: "1" });
  const empId = emp.data.values?.[0]?.id;
  console.log("Employee ID:", empId);

  // TEST A: Create project-specific activity via POST /project/projectActivity with inline activity
  console.log("\n=== TEST A: Create project + project-specific activity via /project/projectActivity ===");

  // Step 1: Create project
  const projA = await api("POST", "/project", {
    name: "TestA2 Specific Activity",
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
  });
  const projAId = projA.data.value?.id;
  console.log(`Project created: id=${projAId} status=${projA.status}`);

  // Step 2: Create project-specific activity via /project/projectActivity with inline activity definition
  const paA = await api("POST", "/project/projectActivity", {
    project: { id: projAId },
    activity: {
      name: "TestA2 Specific Activity",
    },
    startDate: "2026-03-22",
  });
  console.log(`ProjectActivity created: status=${paA.status}`);
  if (paA.data.value) {
    console.log(`  paId=${paA.data.value.id}`);
    console.log(`  activity: id=${paA.data.value.activity?.id} name=${paA.data.value.activity?.name}`);
  } else {
    console.log(`  Response:`, JSON.stringify(paA.data).slice(0, 500));
  }

  // Step 3: Query the project to see activities
  const checkA = await api("GET", `/project/${projAId}`, undefined, {
    fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral,isProjectActivity))"
  });
  console.log(`\nProject A after linking:`);
  console.log(`  gpapOnly=${checkA.data.value?.generalProjectActivitiesPerProjectOnly}`);
  console.log(`  projectActivities:`);
  for (const pa of checkA.data.value?.projectActivities || []) {
    console.log(`    id=${pa.id} activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral} isProjectActivity=${pa.activity?.isProjectActivity}`);
  }

  // Also check the activity itself
  if (paA.data.value?.activity?.id) {
    const actCheck = await api("GET", `/activity/${paA.data.value.activity.id}`, undefined, {
      fields: "id,name,activityType,isGeneral,isProjectActivity,isTask"
    });
    console.log(`  Direct activity query: type=${actCheck.data.value?.activityType} isGeneral=${actCheck.data.value?.isGeneral} isProjectActivity=${actCheck.data.value?.isProjectActivity}`);
  }

  // TEST B: Current approach (for comparison) - standalone general activity + link
  console.log("\n=== TEST B: Current approach (standalone PROJECT_GENERAL_ACTIVITY + link) ===");

  const projB = await api("POST", "/project", {
    name: "TestB2 General Activity",
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    // generalProjectActivitiesPerProjectOnly: false (default)
  });
  const projBId = projB.data.value?.id;
  console.log(`Project created: id=${projBId}`);

  const actB = await api("POST", "/activity", {
    name: "TestB2 General Activity",
    activityType: "PROJECT_GENERAL_ACTIVITY",
    isChargeable: false,
  });
  const actBId = actB.data.value?.id;
  console.log(`Activity created: id=${actBId} type=${actB.data.value?.activityType} isGeneral=${actB.data.value?.isGeneral}`);

  await api("POST", "/project/projectActivity", {
    project: { id: projBId },
    activity: { id: actBId },
    startDate: "2026-03-22",
  });

  const checkB = await api("GET", `/project/${projBId}`, undefined, {
    fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral,isProjectActivity))"
  });
  console.log(`Project B after linking:`);
  console.log(`  gpapOnly=${checkB.data.value?.generalProjectActivitiesPerProjectOnly}`);
  console.log(`  projectActivities:`);
  for (const pa of checkB.data.value?.projectActivities || []) {
    console.log(`    id=${pa.id} activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
  }

  // TEST C: Full simulation of the correct Task 28 flow
  console.log("\n=== TEST C: Full Task 28 simulation (SEQUENTIAL, gpapOnly=true) ===");

  const accounts = [
    { number: "7100", name: "Bilgodtgjørelse oppgavepliktig", increase: 7000 },
    { number: "6500", name: "Motordrevet verktøy", increase: 5600 },
    { number: "5000", name: "Lønn til ansatte", increase: 5000 },
  ];

  const createdProjects: { id: number; name: string; activityId?: number }[] = [];

  for (const acct of accounts) {
    console.log(`\n  Creating project "${acct.name}" (${acct.number}, +${acct.increase})...`);

    // Create project with gpapOnly=true
    const proj = await api("POST", "/project", {
      name: acct.name,
      projectManager: { id: empId },
      startDate: "2026-03-22",
      isInternal: true,
      generalProjectActivitiesPerProjectOnly: true,
    });
    const projId = proj.data.value?.id;
    const projNum = proj.data.value?.number;
    console.log(`    project: id=${projId} number=${projNum} gpapOnly=${proj.data.value?.generalProjectActivitiesPerProjectOnly}`);

    // Create activity and link
    const act = await api("POST", "/activity", {
      name: acct.name,
      activityType: "PROJECT_GENERAL_ACTIVITY",
      isChargeable: false,
    });
    const actId = act.data.value?.id;
    console.log(`    activity: id=${actId} type=${act.data.value?.activityType}`);

    const link = await api("POST", "/project/projectActivity", {
      project: { id: projId },
      activity: { id: actId },
      startDate: "2026-03-22",
    });
    console.log(`    linked: status=${link.status}`);

    createdProjects.push({ id: projId, name: acct.name, activityId: actId });
  }

  // Verify all 3 projects
  console.log("\n  --- Verification ---");
  for (const p of createdProjects) {
    const check = await api("GET", `/project/${p.id}`, undefined, {
      fields: "id,name,number,isInternal,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
    });
    const v = check.data.value;
    console.log(`  Project "${v?.name}" (num=${v?.number}):`);
    console.log(`    isInternal=${v?.isInternal} gpapOnly=${v?.generalProjectActivitiesPerProjectOnly}`);
    console.log(`    projectActivities count=${v?.projectActivities?.length}`);
    for (const pa of v?.projectActivities || []) {
      console.log(`      activity: name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
    }
  }

  // Also check: what does GET /project?isInternal=true return for our new projects?
  console.log("\n  --- How evaluator might query ---");
  const allInternal = await api("GET", "/project", undefined, {
    isInternal: "true",
    fields: "id,name,number,projectActivities(id,activity(id,name)),generalProjectActivitiesPerProjectOnly",
    count: "100"
  });
  console.log(`  Total internal projects: ${allInternal.data.fullResultSize}`);

  // Filter to our test projects
  const ourProjects = (allInternal.data.values || []).filter((p: any) =>
    createdProjects.some(cp => cp.id === p.id)
  );
  console.log(`  Our 3 projects in the list:`);
  for (const p of ourProjects) {
    console.log(`    id=${p.id} num=${p.number} name="${p.name}" gpapOnly=${p.generalProjectActivitiesPerProjectOnly} activities=${p.projectActivities?.length}`);
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
