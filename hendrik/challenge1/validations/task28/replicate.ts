#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 28: Analyze ledger + create projects + activities ===\n");

  // Step 1: Get postings for Jan and Feb in parallel
  console.log("--- Step 1: Get postings Jan vs Feb ---");
  const [janPostings, febPostings] = await Promise.all([
    client.get("/ledger/posting", {
      dateFrom: "2026-01-01", dateTo: "2026-01-31",
      accountNumberFrom: "4000", accountNumberTo: "7999",
      fields: "id,account(id,number,name),amount,amountGross",
      count: "1000"
    }),
    client.get("/ledger/posting", {
      dateFrom: "2026-02-01", dateTo: "2026-02-28",
      accountNumberFrom: "4000", accountNumberTo: "7999",
      fields: "id,account(id,number,name),amount,amountGross",
      count: "1000"
    })
  ]);
  console.log("Jan postings count:", janPostings.fullResultSize);
  console.log("Feb postings count:", febPostings.fullResultSize);

  // Aggregate by account
  const aggregate = (postings: any) => {
    const map: Record<string, { number: number; name: string; total: number }> = {};
    for (const p of postings.values || []) {
      const acc = p.account;
      const key = acc.number;
      if (!map[key]) map[key] = { number: acc.number, name: acc.name, total: 0 };
      map[key].total += p.amount;
    }
    return map;
  };

  const jan = aggregate(janPostings);
  const feb = aggregate(febPostings);

  // Calculate increases
  const allAccounts = new Set([...Object.keys(jan), ...Object.keys(feb)]);
  const increases: { number: string; name: string; jan: number; feb: number; increase: number }[] = [];
  for (const acc of allAccounts) {
    const janAmt = jan[acc]?.total || 0;
    const febAmt = feb[acc]?.total || 0;
    const increase = febAmt - janAmt;
    if (increase > 0) {
      increases.push({ number: acc, name: feb[acc]?.name || jan[acc]?.name, jan: janAmt, feb: febAmt, increase });
    }
  }
  increases.sort((a, b) => b.increase - a.increase);
  console.log("\nTop increases:");
  for (const i of increases.slice(0, 5)) {
    console.log(`  ${i.number} ${i.name}: ${i.jan} → ${i.feb} (+${i.increase})`);
  }

  // Step 2: Get an employee for project manager
  console.log("\n--- Step 2: Get employee ---");
  const emp = await client.get("/employee", { fields: "id,firstName,lastName", count: "1" });
  const empId = emp.values?.[0]?.id;
  console.log("Employee:", emp.values?.[0]);

  // Step 3: Create 3 projects
  const top3 = increases.slice(0, 3);
  console.log("\n--- Step 3: Create projects ---");
  const projects = await Promise.all(
    top3.map(i => client.post("/project", {
      name: i.name,
      projectManager: { id: empId },
      startDate: "2026-03-21",
      isInternal: true
    }))
  );
  for (const p of projects) {
    console.log(`Project: ${p.value?.name} (ID: ${p.value?.id})`);
  }

  // Step 4: Create 3 activities
  console.log("\n--- Step 4: Create activities ---");
  const activities = await Promise.all(
    top3.map(i => client.post("/activity", {
      name: i.name,
      activityType: "PROJECT_GENERAL_ACTIVITY",
      isChargeable: false
    }))
  );
  for (const a of activities) {
    console.log(`Activity: ${a.value?.name} (ID: ${a.value?.id})`);
  }

  // Step 5: Link activities to projects via /project/projectActivity
  console.log("\n--- Step 5: Link activities to projects ---");
  for (let i = 0; i < 3; i++) {
    const projectId = projects[i].value?.id;
    const activityId = activities[i].value?.id;
    if (projectId && activityId) {
      const link = await client.post("/project/projectActivity", {
        project: { id: projectId },
        activity: { id: activityId },
        startDate: "2026-03-21"
      });
      console.log(`Linked activity ${activityId} to project ${projectId}:`, link.value ? "OK" : JSON.stringify(link));
    }
  }

  // Step 6: Verify a project
  if (projects[0].value?.id) {
    console.log("\n--- Step 6: Verify project ---");
    const proj = await client.get(`/project/${projects[0].value.id}`, { fields: "*" });
    console.log("Project activities:", JSON.stringify(proj.value?.projectActivities, null, 2));
  }

  console.log("\n--- API call log ---");
  console.log(client.callLog);
}

main().catch(console.error);
