#!/usr/bin/env bun
/**
 * Task 28 test v3: Clean test with unique names + test inline activity creation
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

const TS = Date.now();

async function main() {
  console.log("=== TASK 28 TEST V3 ===\n");

  const emp = await api("GET", "/employee", undefined, { fields: "id", count: "1" });
  const empId = emp.data.values?.[0]?.id;

  // TEST 1: Inline project-specific activity via POST /project/projectActivity
  console.log("=== TEST 1: Inline PROJECT_SPECIFIC activity ===");
  const proj1 = await api("POST", "/project", {
    name: `T1 Inline Specific ${TS}`,
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
  });
  const p1Id = proj1.data.value?.id;
  console.log(`Project: id=${p1Id}`);

  // Try creating project-specific activity inline with activityType
  const pa1 = await api("POST", "/project/projectActivity", {
    project: { id: p1Id },
    activity: {
      name: `T1 Inline Specific ${TS}`,
      activityType: "PROJECT_SPECIFIC_ACTIVITY",
    },
    startDate: "2026-03-22",
  });
  console.log(`ProjectActivity: status=${pa1.status}`);
  if (pa1.data.value) {
    const act = pa1.data.value.activity;
    console.log(`  activity: id=${act?.id} name="${act?.name}" type=${act?.activityType}`);
    // Fetch activity details
    if (act?.id) {
      const actDetail = await api("GET", `/activity/${act.id}`, undefined, {
        fields: "id,name,activityType,isGeneral,isProjectActivity"
      });
      const a = actDetail.data.value;
      console.log(`  activity detail: type=${a?.activityType} isGeneral=${a?.isGeneral} isProjectActivity=${a?.isProjectActivity}`);
    }
  }

  // Check project
  const check1 = await api("GET", `/project/${p1Id}`, undefined, {
    fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
  });
  console.log(`Project check: gpapOnly=${check1.data.value?.generalProjectActivitiesPerProjectOnly} activities=${check1.data.value?.projectActivities?.length}`);
  for (const pa of check1.data.value?.projectActivities || []) {
    console.log(`  ${pa.activity?.name} type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
  }

  // TEST 2: Current approach with gpapOnly=TRUE (new improvement)
  console.log("\n=== TEST 2: Current approach + gpapOnly=TRUE ===");
  const proj2 = await api("POST", "/project", {
    name: `T2 General gpapTrue ${TS}`,
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
  });
  const p2Id = proj2.data.value?.id;

  const act2 = await api("POST", "/activity", {
    name: `T2 General gpapTrue ${TS}`,
    activityType: "PROJECT_GENERAL_ACTIVITY",
    isChargeable: false,
  });
  const a2Id = act2.data.value?.id;

  await api("POST", "/project/projectActivity", {
    project: { id: p2Id },
    activity: { id: a2Id },
    startDate: "2026-03-22",
  });

  const check2 = await api("GET", `/project/${p2Id}`, undefined, {
    fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
  });
  console.log(`Project check: gpapOnly=${check2.data.value?.generalProjectActivitiesPerProjectOnly} activities=${check2.data.value?.projectActivities?.length}`);
  for (const pa of check2.data.value?.projectActivities || []) {
    console.log(`  ${pa.activity?.name} type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
  }

  // TEST 3: Current approach with gpapOnly=FALSE (current behavior)
  console.log("\n=== TEST 3: Current approach + gpapOnly=FALSE (current buggy behavior) ===");
  const proj3 = await api("POST", "/project", {
    name: `T3 General gpapFalse ${TS}`,
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    // generalProjectActivitiesPerProjectOnly defaults to false
  });
  const p3Id = proj3.data.value?.id;

  const act3 = await api("POST", "/activity", {
    name: `T3 General gpapFalse ${TS}`,
    activityType: "PROJECT_GENERAL_ACTIVITY",
    isChargeable: false,
  });
  const a3Id = act3.data.value?.id;

  await api("POST", "/project/projectActivity", {
    project: { id: p3Id },
    activity: { id: a3Id },
    startDate: "2026-03-22",
  });

  const check3 = await api("GET", `/project/${p3Id}`, undefined, {
    fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
  });
  console.log(`Project check: gpapOnly=${check3.data.value?.generalProjectActivitiesPerProjectOnly} activities=${check3.data.value?.projectActivities?.length}`);
  for (const pa of check3.data.value?.projectActivities || []) {
    console.log(`  ${pa.activity?.name} type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
  }

  // TEST 4: Inline creation via POST /project with projectActivities array
  console.log("\n=== TEST 4: Inline creation via POST /project body ===");
  const proj4 = await api("POST", "/project", {
    name: `T4 Inline Via Project ${TS}`,
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
    projectActivities: [
      {
        activity: {
          name: `T4 Inline Via Project ${TS}`,
          activityType: "PROJECT_GENERAL_ACTIVITY",
          isChargeable: false,
        },
        startDate: "2026-03-22",
      },
    ],
  });
  const p4Id = proj4.data.value?.id;
  console.log(`Project: status=${proj4.status} id=${p4Id}`);
  console.log(`  gpapOnly=${proj4.data.value?.generalProjectActivitiesPerProjectOnly}`);
  console.log(`  projectActivities in response: ${proj4.data.value?.projectActivities?.length}`);

  if (p4Id) {
    const check4 = await api("GET", `/project/${p4Id}`, undefined, {
      fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))"
    });
    console.log(`Project check: activities=${check4.data.value?.projectActivities?.length}`);
    for (const pa of check4.data.value?.projectActivities || []) {
      console.log(`  ${pa.activity?.name} type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
    }
  }

  // COMPARISON: How many activities does each project see?
  console.log("\n=== COMPARISON: Activity visibility per project ===");
  const allProjects = [
    { id: p1Id, name: "T1 Specific+gpapTrue" },
    { id: p2Id, name: "T2 General+gpapTrue" },
    { id: p3Id, name: "T3 General+gpapFalse" },
    { id: p4Id, name: "T4 Inline+gpapTrue" },
  ];

  for (const p of allProjects) {
    if (!p.id) continue;
    const check = await api("GET", `/project/${p.id}`, undefined, {
      fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name))"
    });
    const v = check.data.value;
    console.log(`${p.name}: gpapOnly=${v?.generalProjectActivitiesPerProjectOnly} linked_activities=${v?.projectActivities?.length}`);
    for (const pa of v?.projectActivities || []) {
      console.log(`  - "${pa.activity?.name}"`);
    }
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
