#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 29: Investigate complete project lifecycle ===\n");

  // The task prompt:
  // 1) Project "Migración Cloud Montaña" budget 219800 NOK, customer Montaña SL (903805021)
  // 2) Timesheet: Ana Rodríguez 36h, Isabel García 69h
  // 3) Supplier cost: 46050 NOK from Luna SL (988327581)
  // 4) Invoice customer for project

  // Agent did 8/11 checks. Let's investigate what might be wrong.

  // Check 1: Does the project exist and is it set up correctly?
  console.log("--- Projects ---");
  const projects = await client.get("/project", {
    fields: "id,name,projectManager(id,firstName,lastName),customer(id,name),budget(amount),projectCategory(id,name),isInternal",
    count: "10"
  });
  for (const p of projects.values || []) {
    console.log(`  Project: ${p.name}, manager: ${p.projectManager?.firstName} ${p.projectManager?.lastName}, customer: ${p.customer?.name}, budget: ${JSON.stringify(p.budget)}, internal: ${p.isInternal}`);
  }

  // Check 2: Employees and their setup
  console.log("\n--- Employees ---");
  const employees = await client.get("/employee", {
    fields: "id,firstName,lastName,email,userType,dateOfBirth,department(id,name)",
    count: "10"
  });
  for (const e of employees.values || []) {
    console.log(`  ${e.firstName} ${e.lastName}: email=${e.email}, userType=${e.userType}, dob=${e.dateOfBirth}, dept=${e.department?.name}`);
  }

  // Check 3: Timesheet entries
  console.log("\n--- Timesheet entries ---");
  const timesheets = await client.get("/timesheet/entry", {
    dateFrom: "2026-01-01", dateTo: "2026-12-31",
    fields: "id,employee(id,firstName,lastName),project(id,name),activity(id,name),date,hours",
    count: "50"
  });
  for (const t of timesheets.values || []) {
    console.log(`  ${t.employee?.firstName} ${t.employee?.lastName}: ${t.hours}h on ${t.date}, project=${t.project?.name}, activity=${t.activity?.name}`);
  }

  // Check 4: Activities available
  console.log("\n--- Activities ---");
  const activities = await client.get("/activity", { fields: "id,name,isChargeable", count: "20" });
  for (const a of activities.values || []) {
    console.log(`  ${a.id}: ${a.name} (chargeable: ${a.isChargeable})`);
  }

  // Check 5: Suppliers
  console.log("\n--- Suppliers ---");
  const suppliers = await client.get("/supplier", {
    fields: "id,name,organizationNumber,email,invoiceEmail",
    count: "10"
  });
  for (const s of suppliers.values || []) {
    console.log(`  ${s.name}: org=${s.organizationNumber}, email=${s.email}, invoiceEmail=${s.invoiceEmail}`);
  }

  // Check 6: Vouchers (supplier invoice)
  console.log("\n--- Vouchers ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2026-01-01", dateTo: "2026-12-31",
    fields: "id,number,date,description",
    count: "20"
  });
  for (const v of vouchers.values || []) {
    console.log(`  Voucher #${v.number}: ${v.description} (${v.date})`);
  }

  // Check 7: Invoices
  console.log("\n--- Invoices ---");
  const invoices = await client.get("/invoice", {
    invoiceDateFrom: "2026-01-01", invoiceDateTo: "2026-12-31",
    fields: "id,invoiceNumber,customer(id,name),amount,amountExcludingVat,invoiceDate,invoiceDueDate",
    count: "20"
  });
  for (const inv of invoices.values || []) {
    console.log(`  Invoice #${inv.invoiceNumber}: ${inv.customer?.name}, amount=${inv.amount}, exclVat=${inv.amountExcludingVat}, date=${inv.invoiceDate}, due=${inv.invoiceDueDate}`);
  }

  // Check 8: Postings with project reference
  console.log("\n--- Postings with project ---");
  const postings = await client.get("/ledger/posting", {
    dateFrom: "2026-01-01", dateTo: "2026-12-31",
    fields: "id,account(id,number,name),amount,amountGross,project(id,name),supplier(id,name),customer(id,name),description,invoiceNumber",
    count: "100"
  });
  for (const p of postings.values || []) {
    if (p.project || p.supplier || p.customer) {
      console.log(`  ${p.account.number} (${p.account.name}): amount=${p.amount}, gross=${p.amountGross}, project=${p.project?.name || '-'}, supplier=${p.supplier?.name || '-'}, customer=${p.customer?.name || '-'}, invoiceNr=${p.invoiceNumber || '-'}, desc=${p.description}`);
    }
  }

  // Check 9: Orders
  console.log("\n--- Orders ---");
  const orders = await client.get("/order", {
    fields: "id,number,customer(id,name),project(id,name),orderDate,invoiceOnAccountVatHigh",
    count: "10"
  });
  for (const o of orders.values || []) {
    console.log(`  Order #${o.number}: customer=${o.customer?.name}, project=${o.project?.name}, date=${o.orderDate}, invoiceOnAccount=${o.invoiceOnAccountVatHigh}`);
  }

  // Check 10: Project activities (linked activities)
  console.log("\n--- Project activities ---");
  const projectId = projects.values?.[0]?.id;
  if (projectId) {
    const projActivities = await client.get("/project/projectActivity", {
      projectId: String(projectId),
      fields: "id,project(id,name),activity(id,name)",
      count: "20"
    });
    console.log(`  Project ${projectId} activities:`, JSON.stringify(projActivities.values?.map((pa: any) => pa.activity?.name)));
  }

  console.log("\n=== Summary ===");
  console.log("8/11 checks pass. Possible failing checks:");
  console.log("- Employee hourlyRate/hourlyCost on timesheet?");
  console.log("- Project budget not set correctly?");
  console.log("- Supplier voucher missing vatType on credit posting?");
  console.log("- Invoice missing project link?");
}

main().catch(console.error);
