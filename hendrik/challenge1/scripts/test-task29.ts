#!/usr/bin/env bun
/**
 * Task 29 investigation: What are checks 5-6 testing?
 * All runs: C1-4 pass, C5-6 fail, C7 pass.
 *
 * Hypotheses to test:
 * 1. Supplier cost amount: is "33250 NOK" incl or excl VAT?
 * 2. Is there a missing project budget update?
 * 3. Are hourly rates needed on the project?
 * 4. Does the order/invoice need different fields?
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
  console.log(`${method} ${path} → ${res.status}`);
  if (res.status >= 400) console.log(`  ERROR:`, JSON.stringify(json).slice(0, 500));
  return { status: res.status, data: json };
}

async function main() {
  console.log("=== TASK 29 INVESTIGATION ===\n");

  // Get baseline data
  const emp = await api("GET", "/employee", undefined, { fields: "id,firstName,lastName,email,userType,dateOfBirth", count: "5" });
  console.log("Employees:");
  for (const e of emp.data.values || []) {
    console.log(`  id=${e.id} ${e.firstName} ${e.lastName} userType=${e.userType} dob=${e.dateOfBirth}`);
  }

  // TEST 1: Check supplier cost posting with BOTH interpretations
  console.log("\n=== TEST 1: Supplier cost — excl vs incl VAT ===");
  const acct4300 = await api("GET", "/ledger/account", undefined, { number: "4300", fields: "id,number,name" });
  const acct2400 = await api("GET", "/ledger/account", undefined, { number: "2400", fields: "id,number,name" });
  const supplier = await api("GET", "/supplier", undefined, { fields: "id,name", count: "1" });

  const acct4300Id = acct4300.data.values?.[0]?.id;
  const acct2400Id = acct2400.data.values?.[0]?.id;
  const supplierId = supplier.data.values?.[0]?.id;

  // Find a project
  const proj = await api("GET", "/project", undefined, { isInternal: "false", fields: "id,name,isFixedPrice,fixedprice", count: "5" });
  const project = (proj.data.values || []).find((p: any) => p.id);
  console.log(`\nProject: id=${project?.id} name="${project?.name}" fixedPrice=${project?.isFixedPrice} budget=${project?.fixedprice}`);

  const supplierCost = 33250; // from task

  // Approach A: excl VAT (current) — gross = 33250 * 1.25 = 41562.5
  console.log(`\nApproach A (excl VAT): gross = ${supplierCost * 1.25}, net on 4300 = ${supplierCost}`);

  // Approach B: incl VAT — gross = 33250, net = 26600
  console.log(`Approach B (incl VAT): gross = ${supplierCost}, net on 4300 = ${supplierCost / 1.25}`);

  // Create voucher with approach A
  if (project && acct4300Id && acct2400Id && supplierId) {
    console.log("\n--- Creating voucher A (excl VAT, gross=41562.5) ---");
    const vA = await api("POST", "/ledger/voucher", {
      date: "2026-03-22",
      description: "Test29A excl VAT",
      postings: [
        { date: "2026-03-22", description: "Test supplier", account: { id: acct4300Id },
          supplier: { id: supplierId }, project: { id: project.id },
          amountGross: supplierCost * 1.25, amountGrossCurrency: supplierCost * 1.25,
          vatType: { id: 1 }, invoiceNumber: "TEST-A", row: 1 },
        { date: "2026-03-22", description: "Test supplier", account: { id: acct2400Id },
          supplier: { id: supplierId },
          amountGross: -(supplierCost * 1.25), amountGrossCurrency: -(supplierCost * 1.25),
          vatType: { id: 0 }, row: 2 },
      ],
    });
    if (vA.status === 201) {
      console.log("  Postings created:");
      for (const p of vA.data.value?.postings || []) {
        console.log(`    ${p.account?.id} amount=${p.amount} amountGross=${p.amountGross} vatType=${p.vatType?.id}`);
      }
    }

    console.log("\n--- Creating voucher B (incl VAT, gross=33250) ---");
    const vB = await api("POST", "/ledger/voucher", {
      date: "2026-03-22",
      description: "Test29B incl VAT",
      postings: [
        { date: "2026-03-22", description: "Test supplier", account: { id: acct4300Id },
          supplier: { id: supplierId }, project: { id: project.id },
          amountGross: supplierCost, amountGrossCurrency: supplierCost,
          vatType: { id: 1 }, invoiceNumber: "TEST-B", row: 1 },
        { date: "2026-03-22", description: "Test supplier", account: { id: acct2400Id },
          supplier: { id: supplierId },
          amountGross: -supplierCost, amountGrossCurrency: -supplierCost,
          vatType: { id: 0 }, row: 2 },
      ],
    });
    if (vB.status === 201) {
      console.log("  Postings created:");
      for (const p of vB.data.value?.postings || []) {
        console.log(`    ${p.account?.id} amount=${p.amount} amountGross=${p.amountGross} vatType=${p.vatType?.id}`);
      }
    }

    // Also try with NO VAT (vatType 0)
    console.log("\n--- Creating voucher C (no VAT, gross=33250, vatType=0) ---");
    const vC = await api("POST", "/ledger/voucher", {
      date: "2026-03-22",
      description: "Test29C no VAT",
      postings: [
        { date: "2026-03-22", description: "Test supplier", account: { id: acct4300Id },
          supplier: { id: supplierId }, project: { id: project.id },
          amountGross: supplierCost, amountGrossCurrency: supplierCost,
          vatType: { id: 0 }, invoiceNumber: "TEST-C", row: 1 },
        { date: "2026-03-22", description: "Test supplier", account: { id: acct2400Id },
          supplier: { id: supplierId },
          amountGross: -supplierCost, amountGrossCurrency: -supplierCost,
          vatType: { id: 0 }, row: 2 },
      ],
    });
    if (vC.status === 201) {
      console.log("  Postings created:");
      for (const p of vC.data.value?.postings || []) {
        console.log(`    ${p.account?.id} amount=${p.amount} amountGross=${p.amountGross} vatType=${p.vatType?.id}`);
      }
    }
  }

  // TEST 2: Check project hourly rates
  console.log("\n=== TEST 2: Project hourly rates ===");
  if (project) {
    const rates = await api("GET", "/project/hourlyRates", undefined, {
      projectId: String(project.id),
      fields: "id,version,project(id),startDate,hourlyRateModel,fixedRate",
    });
    console.log("Hourly rates:", JSON.stringify(rates.data.values || rates.data, null, 2).slice(0, 500));
  }

  // TEST 3: Check what project fields the evaluator might look at
  console.log("\n=== TEST 3: Full project details ===");
  if (project) {
    const full = await api("GET", `/project/${project.id}`, undefined, {
      fields: "id,name,isFixedPrice,fixedprice,isInternal,projectActivities(id,activity(id,name)),projectHourlyRates(id)"
    });
    const v = full.data.value;
    console.log(`  isFixedPrice=${v?.isFixedPrice} fixedprice=${v?.fixedprice}`);
    console.log(`  projectActivities: ${v?.projectActivities?.length}`);
    console.log(`  projectHourlyRates: ${v?.projectHourlyRates?.length}`);
  }

  // TEST 4: Check if supplierInvoice is expected instead of ledger voucher
  console.log("\n=== TEST 4: Can we use POST /supplierInvoice instead of voucher? ===");
  if (supplierId && acct4300Id && project) {
    const si = await api("POST", "/supplierInvoice", {
      invoiceDate: "2026-03-22",
      invoiceDueDate: "2026-04-05",
      supplier: { id: supplierId },
      invoiceNumber: "SUP-TEST-29",
      amountCurrency: -supplierCost,
      voucher: {
        date: "2026-03-22",
        description: "Supplier invoice test",
        postings: [
          { date: "2026-03-22", description: "Supplier cost",
            account: { id: acct4300Id }, supplier: { id: supplierId },
            project: { id: project.id },
            amountGross: supplierCost, amountGrossCurrency: supplierCost,
            vatType: { id: 1 }, invoiceNumber: "SUP-TEST-29", row: 1 },
          { date: "2026-03-22", description: "Supplier cost",
            account: { id: acct2400Id }, supplier: { id: supplierId },
            amountGross: -supplierCost, amountGrossCurrency: -supplierCost,
            vatType: { id: 0 }, row: 2 },
        ],
      },
    });
    console.log(`  supplierInvoice: status=${si.status}`);
    if (si.status === 201) {
      console.log(`  id=${si.data.value?.id} voucher=${si.data.value?.voucher?.id}`);
    }
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
