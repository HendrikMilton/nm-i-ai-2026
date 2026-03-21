#!/usr/bin/env bun
/**
 * Test different approaches for registering supplier invoices in Tripletex sandbox.
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
  let json;
  try { json = JSON.parse(text); } catch { json = { raw: text }; }
  console.log(`${method} ${path} → ${res.status}`);
  if (res.status >= 400) console.log("  ERROR:", JSON.stringify(json, null, 2).slice(0, 500));
  return { status: res.status, data: json };
}

async function main() {
  // Setup: find a supplier and expense account
  console.log("=== SETUP ===");

  let supplierId: number;
  const suppliers = await api("GET", "/supplier", undefined, { fields: "id,name", count: "1" });
  if (suppliers.data.fullResultSize === 0) {
    // Create a test supplier
    const s = await api("POST", "/supplier", { name: "Test Supplier AS", isSupplier: true });
    supplierId = s.data.value.id;
  } else {
    supplierId = suppliers.data.values[0].id;
  }
  console.log(`  Supplier ID: ${supplierId}`);

  const acc6540 = await api("GET", "/ledger/account", undefined, { number: "6540", fields: "id,number,name" });
  const expenseAccountId = acc6540.data.values[0].id;
  console.log(`  Expense account: ${expenseAccountId}`);

  const acc2400 = await api("GET", "/ledger/account", undefined, { number: "2400", fields: "id,number,name" });
  const apAccountId = acc2400.data.values[0].id;
  console.log(`  AP account: ${apAccountId}`);

  const today = new Date().toISOString().split("T")[0];

  // ========================================
  // TEST 1: Basic voucher (what we did before)
  // ========================================
  console.log("\n=== TEST 1: Basic voucher with vendorInvoiceNumber ===");
  const t1 = await api("POST", "/ledger/voucher", {
    date: today,
    description: "TEST-INV-001 - Test supplier invoice",
    vendorInvoiceNumber: "TEST-INV-001",
    postings: [
      { date: today, account: { id: expenseAccountId }, supplier: { id: supplierId }, amountGross: 10000, amountGrossCurrency: 10000, vatType: { id: 1 }, description: "Test expense", row: 1 },
      { date: today, account: { id: apAccountId }, supplier: { id: supplierId }, amountGross: -10000, amountGrossCurrency: -10000, description: "Test expense", row: 2 },
    ],
  });
  if (t1.status < 300) {
    const voucherId = t1.data.value.id;
    console.log(`  Voucher created: ${voucherId}`);
    console.log(`  supplierVoucherType: ${t1.data.value.supplierVoucherType}`);
    console.log(`  vendorInvoiceNumber: ${t1.data.value.vendorInvoiceNumber}`);

    // Check if a supplierInvoice was auto-created
    const si = await api("GET", "/supplierInvoice", undefined, { fields: "id,invoiceNumber,supplier,voucher", count: "10" });
    console.log(`  SupplierInvoices found: ${si.data.fullResultSize}`);
    if (si.data.values?.length > 0) {
      console.log(`  Latest:`, JSON.stringify(si.data.values[0], null, 2).slice(0, 300));
    }
  }

  // ========================================
  // TEST 2: Voucher with invoiceNumber on posting
  // ========================================
  console.log("\n=== TEST 2: Voucher with invoiceNumber on posting ===");
  const t2 = await api("POST", "/ledger/voucher", {
    date: today,
    description: "TEST-INV-002",
    vendorInvoiceNumber: "TEST-INV-002",
    postings: [
      { date: today, account: { id: expenseAccountId }, supplier: { id: supplierId }, amountGross: 5000, amountGrossCurrency: 5000, vatType: { id: 1 }, description: "Test 2", row: 1, invoiceNumber: "TEST-INV-002" },
      { date: today, account: { id: apAccountId }, supplier: { id: supplierId }, amountGross: -5000, amountGrossCurrency: -5000, description: "Test 2", row: 2 },
    ],
  });
  if (t2.status < 300) {
    console.log(`  Voucher created: ${t2.data.value.id}`);
    console.log(`  supplierVoucherType: ${t2.data.value.supplierVoucherType}`);
  }

  // ========================================
  // TEST 3: Check supplierInvoice endpoints
  // ========================================
  console.log("\n=== TEST 3: Check existing supplierInvoices ===");
  const si3 = await api("GET", "/supplierInvoice", undefined, {
    fields: "id,invoiceNumber,invoiceDate,supplier,voucher,amount,amountExcludingVat",
    count: "10",
    invoiceDateFrom: "2020-01-01",
    invoiceDateTo: today
  });
  console.log(`  Total: ${si3.data.fullResultSize}`);
  if (si3.data.values?.length > 0) {
    for (const inv of si3.data.values) {
      console.log(`  - ID:${inv.id} num:${inv.invoiceNumber} amount:${inv.amount} exVat:${inv.amountExcludingVat}`);
    }
  }

  // ========================================
  // TEST 4: Try POST to create supplier invoice directly (might not exist)
  // ========================================
  console.log("\n=== TEST 4: Try direct POST /supplierInvoice ===");
  const t4 = await api("POST", "/supplierInvoice", {
    invoiceNumber: "TEST-INV-003",
    invoiceDate: today,
    invoiceDueDate: today,
    supplier: { id: supplierId },
  });

  // ========================================
  // TEST 5: Try the "Easy guidance" flow - POST /ledger/voucher with supplier on credit line only
  // ========================================
  console.log("\n=== TEST 5: Supplier only on credit (AP) line ===");
  const t5 = await api("POST", "/ledger/voucher", {
    date: today,
    description: "TEST-INV-005",
    vendorInvoiceNumber: "TEST-INV-005",
    postings: [
      { date: today, account: { id: expenseAccountId }, amountGross: 7500, amountGrossCurrency: 7500, vatType: { id: 1 }, description: "Test 5", row: 1 },
      { date: today, account: { id: apAccountId }, supplier: { id: supplierId }, amountGross: -7500, amountGrossCurrency: -7500, description: "Test 5", row: 2 },
    ],
  });
  if (t5.status < 300) {
    console.log(`  Voucher created: ${t5.data.value.id}`);
    console.log(`  supplierVoucherType: ${t5.data.value.supplierVoucherType}`);

    // Check supplierInvoice again
    const si5 = await api("GET", "/supplierInvoice", undefined, { fields: "id,invoiceNumber", count: "5" });
    console.log(`  SupplierInvoices after: ${si5.data.fullResultSize}`);
  }
}

main().catch(console.error);
