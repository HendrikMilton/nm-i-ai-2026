#!/usr/bin/env bun
/**
 * Task 28 sandbox test: Test different project/activity creation approaches
 * to find which one the evaluator expects.
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

async function main() {
  console.log("=== TASK 28 SANDBOX TESTS ===\n");

  // 0. Get employee for project manager
  const emp = await api("GET", "/employee", undefined, { fields: "id", count: "1" });
  const empId = emp.data.values?.[0]?.id;
  console.log("Employee ID:", empId);

  // 1. Check pre-existing activities
  console.log("\n--- TEST 1: Pre-existing activities ---");
  const activities = await api("GET", "/activity", undefined, { count: "100", fields: "id,name,activityType,isGeneral,isProjectActivity" });
  console.log("All activities in system:");
  for (const a of activities.data.values || []) {
    console.log(`  id=${a.id} name="${a.name}" type=${a.activityType} isGeneral=${a.isGeneral} isProjectActivity=${a.isProjectActivity}`);
  }

  // 2. Check existing projects
  console.log("\n--- TEST 2: Existing internal projects ---");
  const projects = await api("GET", "/project", undefined, { isInternal: "true", fields: "id,name,number,projectActivities(id,activity(id,name,activityType)),generalProjectActivitiesPerProjectOnly", count: "20" });
  console.log("Internal projects:");
  for (const p of projects.data.values || []) {
    console.log(`  id=${p.id} num=${p.number} name="${p.name}" gpapOnly=${p.generalProjectActivitiesPerProjectOnly}`);
    if (p.projectActivities?.length) {
      for (const pa of p.projectActivities) {
        console.log(`    activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType}`);
      }
    } else {
      console.log(`    NO linked activities`);
    }
  }

  // 3. TEST A: Create project with generalProjectActivitiesPerProjectOnly=true
  console.log("\n--- TEST 3A: Project with generalProjectActivitiesPerProjectOnly=TRUE ---");
  const projA = await api("POST", "/project", {
    name: "TestA gpapOnly true",
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
  });
  const projAId = projA.data.value?.id;
  console.log(`Created project: id=${projAId} gpapOnly=${projA.data.value?.generalProjectActivitiesPerProjectOnly}`);

  // Create activity and link it
  const actA = await api("POST", "/activity", {
    name: "TestA gpapOnly true",
    activityType: "PROJECT_GENERAL_ACTIVITY",
    isChargeable: false,
  });
  const actAId = actA.data.value?.id;
  console.log(`Created activity: id=${actAId} type=${actA.data.value?.activityType} isGeneral=${actA.data.value?.isGeneral}`);

  const linkA = await api("POST", "/project/projectActivity", {
    project: { id: projAId },
    activity: { id: actAId },
    startDate: "2026-03-22",
  });
  console.log(`Linked: status=${linkA.status}`);

  // Now query the project to see what activities appear
  const checkA = await api("GET", `/project/${projAId}`, undefined, { fields: "id,name,generalProjectActivitiesPerProjectOnly,projectActivities(id,activity(id,name,activityType,isGeneral))" });
  console.log("Project A queried:");
  console.log(`  gpapOnly=${checkA.data.value?.generalProjectActivitiesPerProjectOnly}`);
  console.log(`  projectActivities count=${checkA.data.value?.projectActivities?.length}`);
  for (const pa of checkA.data.value?.projectActivities || []) {
    console.log(`    activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
  }

  // 4. TEST B: Create project with inline projectActivities
  console.log("\n--- TEST 3B: Project with INLINE projectActivities ---");
  const projB = await api("POST", "/project", {
    name: "TestB inline activity",
    projectManager: { id: empId },
    startDate: "2026-03-22",
    isInternal: true,
    generalProjectActivitiesPerProjectOnly: true,
    projectActivities: [
      {
        activity: {
          name: "TestB inline activity",
          activityType: "PROJECT_GENERAL_ACTIVITY",
          isChargeable: false,
        },
        startDate: "2026-03-22",
      },
    ],
  });
  console.log(`Created project B: status=${projB.status}`);
  const projBId = projB.data.value?.id;
  if (projBId) {
    console.log(`  id=${projBId} gpapOnly=${projB.data.value?.generalProjectActivitiesPerProjectOnly}`);
    console.log(`  projectActivities count=${projB.data.value?.projectActivities?.length}`);
    for (const pa of projB.data.value?.projectActivities || []) {
      console.log(`    activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType}`);
    }
  } else {
    console.log("  FAILED - response:", JSON.stringify(projB.data).slice(0, 500));
  }

  // 5. TEST C: Create project with GENERAL_ACTIVITY type instead of PROJECT_GENERAL_ACTIVITY
  console.log("\n--- TEST 3C: Activity with GENERAL_ACTIVITY type ---");
  const actC = await api("POST", "/activity", {
    name: "TestC general type",
    activityType: "GENERAL_ACTIVITY",
    isChargeable: false,
  });
  console.log(`Created activity C: status=${actC.status}`);
  if (actC.data.value) {
    console.log(`  id=${actC.data.value.id} type=${actC.data.value.activityType} isGeneral=${actC.data.value.isGeneral} isProjectActivity=${actC.data.value.isProjectActivity}`);
  } else {
    console.log("  FAILED:", JSON.stringify(actC.data).slice(0, 300));
  }

  // 6. TEST D: Create project with PROJECT_SPECIFIC_ACTIVITY type
  console.log("\n--- TEST 3D: Activity with PROJECT_SPECIFIC_ACTIVITY type ---");
  const actD = await api("POST", "/activity", {
    name: "TestD specific type",
    activityType: "PROJECT_SPECIFIC_ACTIVITY",
    isChargeable: false,
  });
  console.log(`Created activity D: status=${actD.status}`);
  if (actD.data.value) {
    console.log(`  id=${actD.data.value.id} type=${actD.data.value.activityType} isGeneral=${actD.data.value.isGeneral} isProjectActivity=${actD.data.value.isProjectActivity}`);
  } else {
    console.log("  FAILED:", JSON.stringify(actD.data).slice(0, 300));
  }

  // 7. TEST E: Check how evaluator might query - GET /project with different field sets
  console.log("\n--- TEST 4: Different ways to query project activities ---");
  if (projAId) {
    // Default fields
    const q1 = await api("GET", `/project/${projAId}`);
    console.log("Default query - projectActivities present:", !!q1.data.value?.projectActivities, "count:", q1.data.value?.projectActivities?.length);

    // With explicit fields
    const q2 = await api("GET", `/project/${projAId}`, undefined, { fields: "id,name,projectActivities" });
    console.log("Explicit fields - projectActivities count:", q2.data.value?.projectActivities?.length);

    // Query project activities directly
    const q3 = await api("GET", "/project/projectActivity", undefined, { projectId: String(projAId), fields: "id,activity(id,name,activityType,isGeneral)" });
    console.log("Direct projectActivity query - count:", q3.data.values?.length);
    for (const pa of q3.data.values || []) {
      console.log(`  activity: id=${pa.activity?.id} name="${pa.activity?.name}" type=${pa.activity?.activityType} isGeneral=${pa.activity?.isGeneral}`);
    }
  }

  // 8. Check ledger data to confirm correct top 3
  console.log("\n--- TEST 5: Verify correct top 3 accounts ---");
  const jan = await api("GET", "/ledger/posting", undefined, { dateFrom: "2026-01-01", dateTo: "2026-01-31", accountNumberFrom: "4000", accountNumberTo: "7999", count: "1000", fields: "id,account(id,number,name),amount" });
  const feb = await api("GET", "/ledger/posting", undefined, { dateFrom: "2026-02-01", dateTo: "2026-02-28", accountNumberFrom: "4000", accountNumberTo: "7999", count: "1000", fields: "id,account(id,number,name),amount" });

  // Aggregate by account
  const aggregate = (entries: any[]) => {
    const m: Record<string, { name: string; total: number }> = {};
    for (const e of entries) {
      const key = String(e.account.number);
      if (!m[key]) m[key] = { name: e.account.name, total: 0 };
      m[key].total += e.amount;
    }
    return m;
  };

  const janTotals = aggregate(jan.data.values || []);
  const febTotals = aggregate(feb.data.values || []);

  console.log("\nIncreases (sorted):");
  const increases: { acct: string; name: string; jan: number; feb: number; increase: number }[] = [];
  for (const acct of Object.keys(febTotals)) {
    const janAmt = janTotals[acct]?.total || 0;
    const febAmt = febTotals[acct]?.total || 0;
    increases.push({ acct, name: febTotals[acct].name, jan: janAmt, feb: febAmt, increase: febAmt - janAmt });
  }
  increases.sort((a, b) => b.increase - a.increase);
  for (const inc of increases) {
    const marker = increases.indexOf(inc) < 3 ? " <<<" : "";
    console.log(`  ${inc.acct} ${inc.name}: ${inc.jan} → ${inc.feb} (+${inc.increase})${marker}`);
  }

  // Cleanup note
  console.log("\n--- NOTE: Test projects created in sandbox. Clean up manually if needed. ---");
}

main().catch(console.error);
