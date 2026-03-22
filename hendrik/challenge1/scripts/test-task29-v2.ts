#!/usr/bin/env bun
/**
 * Task 29 test v2: Test supplierInvoice approach vs voucher approach.
 * Hypothesis: evaluator checks for supplierInvoice, not just a voucher.
 *
 * Also test: is the supplier cost amount incl or excl VAT?
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
  console.log("=== TASK 29 SUPPLIER INVOICE TEST ===\n");

  // Get accounts
  const [a4300, a2400, supplierR, projR] = await Promise.all([
    api("GET", "/ledger/account", undefined, { number: "4300", fields: "id,number,name" }),
    api("GET", "/ledger/account", undefined, { number: "2400", fields: "id,number,name" }),
    api("GET", "/supplier", undefined, { fields: "id,name", count: "1" }),
    api("GET", "/project", undefined, { isInternal: "false", fields: "id,name", count: "1" }),
  ]);

  const acct4300Id = a4300.data.values?.[0]?.id;
  const acct2400Id = a2400.data.values?.[0]?.id;
  const suppId = supplierR.data.values?.[0]?.id;
  const suppName = supplierR.data.values?.[0]?.name;
  const projId = projR.data.values?.[0]?.id;
  const projName = projR.data.values?.[0]?.name;
  console.log(`Supplier: ${suppId} "${suppName}"`);
  console.log(`Project: ${projId} "${projName}"`);
  console.log(`Account 4300: ${acct4300Id}, 2400: ${acct2400Id}\n`);

  const supplierCost = 33250;

  // TEST A: POST /supplierInvoice with supplier cost EXCL VAT (gross = cost × 1.25)
  console.log("=== TEST A: supplierInvoice, cost EXCL VAT (gross=41562.5) ===");
  const siA = await api("POST", "/supplierInvoice", {
    invoiceDate: "2026-03-22",
    invoiceDueDate: "2026-04-05",
    supplier: { id: suppId },
    invoiceNumber: `T29A-${Date.now()}`,
    amountCurrency: -(supplierCost * 1.25),
    voucher: {
      date: "2026-03-22",
      description: `${suppName} - supplier cost`,
      postings: [
        { date: "2026-03-22", description: "Supplier cost",
          account: { id: acct4300Id }, supplier: { id: suppId },
          project: { id: projId },
          amountGross: supplierCost * 1.25, amountGrossCurrency: supplierCost * 1.25,
          vatType: { id: 1 }, row: 1 },
        { date: "2026-03-22", description: "Supplier cost",
          account: { id: acct2400Id }, supplier: { id: suppId },
          amountGross: -(supplierCost * 1.25), amountGrossCurrency: -(supplierCost * 1.25),
          vatType: { id: 0 }, row: 2 },
      ],
    },
  });
  if (siA.status === 201) {
    const v = siA.data.value;
    console.log(`  Created: id=${v?.id} amount=${v?.amountCurrency}`);
    // Check the voucher postings
    if (v?.voucher?.id) {
      const voucher = await api("GET", `/ledger/voucher/${v.voucher.id}`, undefined, {
        fields: "id,postings(id,account(id,number),amount,amountGross,project(id,name))"
      });
      for (const p of voucher.data.value?.postings || []) {
        console.log(`    acct=${p.account?.number} amount=${p.amount} gross=${p.amountGross} project=${p.project?.name || 'none'}`);
      }
    }
  }

  // TEST B: POST /supplierInvoice with supplier cost INCL VAT (gross = cost)
  console.log("\n=== TEST B: supplierInvoice, cost INCL VAT (gross=33250) ===");
  const siB = await api("POST", "/supplierInvoice", {
    invoiceDate: "2026-03-22",
    invoiceDueDate: "2026-04-05",
    supplier: { id: suppId },
    invoiceNumber: `T29B-${Date.now()}`,
    amountCurrency: -supplierCost,
    voucher: {
      date: "2026-03-22",
      description: `${suppName} - supplier cost`,
      postings: [
        { date: "2026-03-22", description: "Supplier cost",
          account: { id: acct4300Id }, supplier: { id: suppId },
          project: { id: projId },
          amountGross: supplierCost, amountGrossCurrency: supplierCost,
          vatType: { id: 1 }, row: 1 },
        { date: "2026-03-22", description: "Supplier cost",
          account: { id: acct2400Id }, supplier: { id: suppId },
          amountGross: -supplierCost, amountGrossCurrency: -supplierCost,
          vatType: { id: 0 }, row: 2 },
      ],
    },
  });
  if (siB.status === 201) {
    const v = siB.data.value;
    console.log(`  Created: id=${v?.id} amount=${v?.amountCurrency}`);
    if (v?.voucher?.id) {
      const voucher = await api("GET", `/ledger/voucher/${v.voucher.id}`, undefined, {
        fields: "id,postings(id,account(id,number),amount,amountGross,project(id,name))"
      });
      for (const p of voucher.data.value?.postings || []) {
        console.log(`    acct=${p.account?.number} amount=${p.amount} gross=${p.amountGross} project=${p.project?.name || 'none'}`);
      }
    }
  }

  // TEST C: Query supplier invoices to see how evaluator might find them
  console.log("\n=== TEST C: How evaluator might query supplier invoices ===");
  const allSI = await api("GET", "/supplierInvoice", undefined, {
    supplierId: String(suppId),
    invoiceDateFrom: "2026-01-01",
    invoiceDateTo: "2026-12-31",
    fields: "id,invoiceNumber,supplier(id,name),amountCurrency,voucher(id)",
    count: "10",
  });
  console.log(`  Supplier invoices found: ${allSI.data.values?.length || 0}`);
  for (const si of allSI.data.values || []) {
    console.log(`    id=${si.id} inv#=${si.invoiceNumber} amount=${si.amountCurrency} voucher=${si.voucher?.id}`);
  }

  // TEST D: Does the evaluator look for vouchers with specific characteristics?
  console.log("\n=== TEST D: Query vouchers for supplier on project ===");
  const vouchersOnProject = await api("GET", "/ledger/posting", undefined, {
    accountNumberFrom: "4300", accountNumberTo: "4300",
    supplierId: String(suppId),
    dateFrom: "2026-03-01", dateTo: "2026-03-31",
    fields: "id,account(number),amount,amountGross,project(id,name),supplier(id,name)",
    count: "20",
  });
  console.log(`  Postings on 4300 for supplier: ${vouchersOnProject.data.values?.length || 0}`);
  for (const p of vouchersOnProject.data.values || []) {
    console.log(`    amount=${p.amount} gross=${p.amountGross} project=${p.project?.name || 'NONE'} supplier=${p.supplier?.name}`);
  }

  // TEST E: Does /supplierInvoice need to be sent to ledger?
  console.log("\n=== TEST E: SupplierInvoice status check ===");
  if (siA.status === 201) {
    const siCheck = await api("GET", `/supplierInvoice/${siA.data.value?.id}`, undefined, {
      fields: "id,invoiceNumber,amountCurrency,supplier(id,name),voucher(id)"
    });
    const v = siCheck.data.value;
    console.log(`  id=${v?.id} inv#=${v?.invoiceNumber} amount=${v?.amountCurrency}`);
    console.log(`  voucher: ${v?.voucher?.id}`);

    // Does it need sendToLedger?
    console.log("\n  Trying PUT /:sendToLedger...");
    const send = await api("PUT", `/ledger/voucher/${v?.voucher?.id}/:sendToLedger`, {});
    console.log(`  sendToLedger: status=${send.status}`);
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
