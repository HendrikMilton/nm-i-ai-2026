#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 29: Test supplier voucher scenarios ===\n");

  // Setup: find existing data
  const [employees, suppliers, projects, activities, acc4300, acc2400] = await Promise.all([
    client.get("/employee", { fields: "id,firstName,lastName,email,userType,dateOfBirth", count: "5" }),
    client.get("/supplier", { fields: "id,name", count: "5" }),
    client.get("/project", { fields: "id,name,version,projectManager(id),isInternal", count: "5" }),
    client.get("/activity", { fields: "id,name,isChargeable", count: "10" }),
    client.get("/ledger/account", { number: "4300", fields: "id,number,name" }),
    client.get("/ledger/account", { number: "2400", fields: "id,number,name" }),
  ]);

  const emp = employees.values?.[0];
  const supplier = suppliers.values?.[0];
  const project = projects.values?.[0];
  const activity = activities.values?.find((a: any) => a.name === "Fakturerbart arbeid") || activities.values?.[0];
  const id4300 = acc4300.values?.[0]?.id;
  const id2400 = acc2400.values?.[0]?.id;

  console.log(`Employee: ${emp?.firstName} ${emp?.lastName} (${emp?.id}), userType=${emp?.userType}, dob=${emp?.dateOfBirth}`);
  console.log(`Supplier: ${supplier?.name} (${supplier?.id})`);
  console.log(`Project: ${project?.name} (${project?.id})`);
  console.log(`Activity: ${activity?.name} (${activity?.id})`);
  console.log(`Account 4300: ${id4300}`);
  console.log(`Account 2400: ${id2400}`);

  if (!supplier || !project || !id4300 || !id2400) {
    console.log("Missing data, creating test supplier and project...");
    return;
  }

  const supplierCost = 34850; // from task prompt

  // ============================================================
  // TEST 1: Supplier cost as-is (excl VAT assumption, *1.25)
  // ============================================================
  console.log("\n--- TEST 1: amountGross = supplierCost * 1.25 (excl VAT) ---");
  const gross1 = supplierCost * 1.25;
  console.log(`  supplierCost=${supplierCost}, gross=${gross1}`);
  const v1 = await client.post("/ledger/voucher", {
    date: "2026-03-21",
    description: "TEST1 - supplier cost excl VAT",
    postings: [
      { date: "2026-03-21", description: "TEST1 debit", account: { id: id4300 }, supplier: { id: supplier.id }, project: { id: project.id }, amountGross: gross1, amountGrossCurrency: gross1, vatType: { id: 1 }, invoiceNumber: "TEST-1", row: 1 },
      { date: "2026-03-21", description: "TEST1 credit", account: { id: id2400 }, supplier: { id: supplier.id }, amountGross: -gross1, amountGrossCurrency: -gross1, vatType: { id: 0 }, row: 2 },
    ]
  });
  const p1 = v1.value?.postings || [];
  for (const p of p1) {
    console.log(`  ${p.account.id}: amount=${p.amount}, gross=${p.amountGross}, vat=${p.vatType?.id}, systemGenerated=${p.systemGenerated}`);
  }

  // ============================================================
  // TEST 2: Supplier cost as-is (incl VAT assumption, raw amount)
  // ============================================================
  console.log("\n--- TEST 2: amountGross = supplierCost (incl VAT) ---");
  const v2 = await client.post("/ledger/voucher", {
    date: "2026-03-21",
    description: "TEST2 - supplier cost incl VAT",
    postings: [
      { date: "2026-03-21", description: "TEST2 debit", account: { id: id4300 }, supplier: { id: supplier.id }, project: { id: project.id }, amountGross: supplierCost, amountGrossCurrency: supplierCost, vatType: { id: 1 }, invoiceNumber: "TEST-2", row: 1 },
      { date: "2026-03-21", description: "TEST2 credit", account: { id: id2400 }, supplier: { id: supplier.id }, amountGross: -supplierCost, amountGrossCurrency: -supplierCost, vatType: { id: 0 }, row: 2 },
    ]
  });
  const p2 = v2.value?.postings || [];
  for (const p of p2) {
    console.log(`  ${p.account.id}: amount=${p.amount}, gross=${p.amountGross}, vat=${p.vatType?.id}, systemGenerated=${p.systemGenerated}`);
  }

  // ============================================================
  // TEST 3: No VAT at all (vatType 0 on both)
  // ============================================================
  console.log("\n--- TEST 3: amountGross = supplierCost, vatType 0 on both ---");
  const v3 = await client.post("/ledger/voucher", {
    date: "2026-03-21",
    description: "TEST3 - no VAT",
    postings: [
      { date: "2026-03-21", description: "TEST3 debit", account: { id: id4300 }, supplier: { id: supplier.id }, project: { id: project.id }, amountGross: supplierCost, amountGrossCurrency: supplierCost, vatType: { id: 0 }, invoiceNumber: "TEST-3", row: 1 },
      { date: "2026-03-21", description: "TEST3 credit", account: { id: id2400 }, supplier: { id: supplier.id }, amountGross: -supplierCost, amountGrossCurrency: -supplierCost, vatType: { id: 0 }, row: 2 },
    ]
  });
  const p3 = v3.value?.postings || [];
  for (const p of p3) {
    console.log(`  ${p.account.id}: amount=${p.amount}, gross=${p.amountGross}, vat=${p.vatType?.id}, systemGenerated=${p.systemGenerated}`);
  }

  // ============================================================
  // TEST 4: Check if timesheet hourlyRate matters
  // ============================================================
  console.log("\n--- TEST 4: Timesheet entry — check hourlyRate ---");
  if (emp && project && activity) {
    // First ensure employee can log time
    if (!emp.userType || emp.userType !== "STANDARD") {
      const fullEmp = await client.get(`/employee/${emp.id}`, { fields: "*" });
      await client.put(`/employee/${emp.id}`, {
        id: emp.id, version: fullEmp.value.version,
        firstName: emp.firstName, lastName: emp.lastName,
        dateOfBirth: emp.dateOfBirth || "1990-01-01",
        userType: "STANDARD"
      });
    }
    const ts = await client.post("/timesheet/entry", {
      employee: { id: emp.id },
      project: { id: project.id },
      activity: { id: activity.id },
      date: "2026-03-21",
      hours: 10,
    });
    console.log(`  hourlyRate=${ts.value?.hourlyRate}, hourlyCost=${ts.value?.hourlyCost}`);
    console.log(`  chargeable=${ts.value?.chargeable}, chargeableHours=${ts.value?.chargeableHours}`);

    // Can we set hourlyRate on the entry?
    console.log("\n--- TEST 4b: Timesheet entry with hourlyRate ---");
    const ts2 = await client.post("/timesheet/entry", {
      employee: { id: emp.id },
      project: { id: project.id },
      activity: { id: activity.id },
      date: "2026-03-22",
      hours: 5,
      hourlyRate: 1650,
    });
    console.log(`  hourlyRate=${ts2.value?.hourlyRate}, hourlyCost=${ts2.value?.hourlyCost}`);
  }

  // ============================================================
  // TEST 5: Check project — can we set budget?
  // ============================================================
  console.log("\n--- TEST 5: Project budget ---");
  const fullProj = await client.get(`/project/${project.id}`, { fields: "*" });
  const projKeys = Object.keys(fullProj.value || {}).filter(k => k.toLowerCase().includes("budget") || k.toLowerCase().includes("amount") || k.toLowerCase().includes("price") || k.toLowerCase().includes("cost"));
  console.log(`  Budget-related fields: ${projKeys.join(", ")}`);
  for (const k of projKeys) {
    console.log(`    ${k}: ${JSON.stringify(fullProj.value[k])}`);
  }

  // ============================================================
  // TEST 6: Check invoice — does it need bank account?
  // ============================================================
  console.log("\n--- TEST 6: Invoice without bank account ---");
  const bank = await client.get("/ledger/account", { number: "1920", fields: "id,bankAccountNumber" });
  console.log(`  Bank 1920 bankAccountNumber: "${bank.values?.[0]?.bankAccountNumber}"`);

  console.log("\n=== SUMMARY ===");
  console.log("Compare TEST 1 vs TEST 2 vs TEST 3 amounts to see which matches evaluator expectations.");
  console.log("Check TEST 4 hourlyRate to see if it affects scoring.");
  console.log("Check TEST 5 for budget fields on project.");
}

main().catch(console.error);
