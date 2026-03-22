#!/usr/bin/env bun
/**
 * Task 25 efficiency test: Test inline order+orderline creation
 * and verify minimum API calls needed.
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
  console.log("=== TASK 25 EFFICIENCY TESTS ===\n");

  // Step 1: Find overdue invoice, account 3400, payment types — parallel
  console.log("--- Step 1: Parallel GETs ---");
  const [invoicesR, acct3400R, payTypesR] = await Promise.all([
    api("GET", "/invoice", undefined, {
      invoiceDateFrom: "2020-01-01", invoiceDateTo: "2026-12-31",
      fields: "id,invoiceNumber,invoiceDate,invoiceDueDate,customer(id,name),amount,amountOutstanding"
    }),
    api("GET", "/ledger/account", undefined, { number: "3400", fields: "id,number,name" }),
    api("GET", "/invoice/paymentType", undefined, { fields: "id,description" }),
  ]);

  const invoices = invoicesR.data.values || [];
  console.log(`  Invoices found: ${invoices.length}`);
  for (const inv of invoices) {
    const overdue = new Date(inv.invoiceDueDate) < new Date() ? "OVERDUE" : "ok";
    console.log(`    #${inv.invoiceNumber} ${inv.customer?.name} due=${inv.invoiceDueDate} outstanding=${inv.amountOutstanding} ${overdue}`);
  }

  const acct3400Id = acct3400R.data.values?.[0]?.id;
  console.log(`  Account 3400 id: ${acct3400Id}`);

  const payTypes = payTypesR.data.values || [];
  console.log(`  Payment types:`, payTypes.map((p: any) => `${p.id}=${p.description}`).join(", "));
  const betaltTilBankId = payTypes.find((p: any) => p.description === "Betalt til bank")?.id;
  console.log(`  "Betalt til bank" id: ${betaltTilBankId}`);

  // Find overdue invoice
  const overdue = invoices.find((inv: any) => new Date(inv.invoiceDueDate) < new Date() && inv.amountOutstanding > 0);
  if (!overdue) {
    console.log("  No overdue invoice found!");
    return;
  }
  console.log(`  Overdue: #${overdue.invoiceNumber} ${overdue.customer?.name} amount=${overdue.amount} outstanding=${overdue.amountOutstanding}`);

  // TEST A: Can we skip account 3400 lookup by passing number instead of id?
  console.log("\n--- TEST A: Create product with account number instead of id ---");
  const prodA = await api("POST", "/product", {
    name: `Test25A Purregebyr ${Date.now()}`,
    number: 99990 + Math.floor(Math.random() * 1000),
    priceExcludingVatCurrency: 70,
    vatType: { id: 0 },
    account: { number: 3400 },  // number instead of id
  });
  if (prodA.status === 201) {
    console.log(`  SUCCESS! Product created with account:{number:3400}`);
    console.log(`  Product id: ${prodA.data.value?.id}, account: ${JSON.stringify(prodA.data.value?.account)}`);
  } else {
    console.log(`  FAILED — need account id lookup`);
  }

  // TEST B: Create product with account id (current approach)
  console.log("\n--- TEST B: Create product with account id (current) ---");
  const prodB = await api("POST", "/product", {
    name: `Test25B Purregebyr ${Date.now()}`,
    number: 99990 + Math.floor(Math.random() * 1000),
    priceExcludingVatCurrency: 70,
    vatType: { id: 0 },
    account: { id: acct3400Id },
  });
  console.log(`  Product id: ${prodB.data.value?.id}`);
  const productId = prodA.status === 201 ? prodA.data.value?.id : prodB.data.value?.id;

  // TEST C: Inline order+orderlines in POST /invoice
  console.log("\n--- TEST C: POST /invoice with INLINE order+orderlines ---");
  const today = new Date().toISOString().split("T")[0];
  const dueDate = new Date(Date.now() + 14 * 86400000).toISOString().split("T")[0];

  const invC = await api("POST", "/invoice", {
    invoiceDate: today,
    invoiceDueDate: dueDate,
    orders: [{
      customer: { id: overdue.customer.id },
      orderDate: today,
      deliveryDate: today,
      orderLines: [{
        product: { id: productId },
        count: 1,
        unitPriceExcludingVatCurrency: 70,
        vatType: { id: 0 },
      }],
    }],
  }, { sendToCustomer: "true" });

  if (invC.status === 201) {
    console.log(`  SUCCESS! Invoice created with inline order+orderlines`);
    console.log(`  Invoice id: ${invC.data.value?.id}, number: ${invC.data.value?.invoiceNumber}`);
    console.log(`  Amount: ${invC.data.value?.amount}, voucher: ${invC.data.value?.voucher?.id}`);
    // Check that the posting went to 3400
    const postings = invC.data.value?.postings || [];
    console.log(`  Postings count: ${postings.length}`);
  } else {
    console.log(`  FAILED — need separate order creation`);
  }

  // TEST D: Register partial payment on overdue invoice
  console.log("\n--- TEST D: Partial payment (5000 on overdue) ---");
  if (betaltTilBankId && overdue) {
    const payD = await api("PUT", `/invoice/${overdue.id}/:payment`, {}, {
      paymentDate: today,
      paymentTypeId: String(betaltTilBankId),
      paidAmount: "5000",
    });
    if (payD.status === 200) {
      console.log(`  SUCCESS! Partial payment registered`);
      console.log(`  New outstanding: ${payD.data.value?.amountOutstanding}`);
    }
  }

  // SUMMARY
  console.log("\n=== SUMMARY ===");
  const canSkipAcct3400 = prodA.status === 201;
  console.log(`Can skip GET /ledger/account?number=3400: ${canSkipAcct3400 ? "YES" : "NO"}`);
  console.log(`Can use inline order+orderlines: ${invC.status === 201 ? "YES" : "NO"}`);

  const minCalls = canSkipAcct3400 ? 5 : 6;
  console.log(`\nMinimum API calls possible: ${minCalls}`);
  if (canSkipAcct3400) {
    console.log("  1. GET /invoice (find overdue) }");
    console.log("  2. GET /invoice/paymentType    } parallel");
    console.log("  3. POST /product (with account:{number:3400})");
    console.log("  4. POST /invoice?sendToCustomer=true (inline order+orderlines)");
    console.log("  5. PUT /invoice/:payment (partial payment)");
  } else {
    console.log("  1. GET /invoice (find overdue)        }");
    console.log("  2. GET /ledger/account?number=3400    } parallel");
    console.log("  3. GET /invoice/paymentType            }");
    console.log("  4. POST /product (with account:{id})");
    console.log("  5. POST /invoice?sendToCustomer=true (inline order+orderlines)");
    console.log("  6. PUT /invoice/:payment (partial payment)");
  }

  console.log("\n=== DONE ===");
}

main().catch(console.error);
