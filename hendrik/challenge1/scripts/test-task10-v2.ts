#!/usr/bin/env bun
/**
 * Task 10 test v2: Can we combine product lookups into 1 call?
 * If we get ALL products in 1 GET instead of 2, total drops from 7→5:
 *   1. GET /customer
 *   2. GET /product (all, count=100)
 *   3. GET /invoice/paymentType
 *   4. POST /invoice (inline)
 *   5. PUT /invoice/:payment
 * Removing GET /ledger/account?number=1920 is free (already wasted).
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
  if (res.status >= 400) console.log(`  ERROR:`, JSON.stringify(json).slice(0, 300));
  return { status: res.status, data: json };
}

async function main() {
  console.log("=== TASK 10 COMBINED PRODUCT LOOKUP TEST ===\n");

  // TEST 1: Get ALL products in one call, then filter
  console.log("--- TEST 1: GET /product with count=100 ---");
  const allProds = await api("GET", "/product", undefined, {
    fields: "id,name,number",
    count: "100",
  });
  console.log(`  Total products: ${allProds.data.fullResultSize}`);
  const products = allProds.data.values || [];
  console.log(`  Returned: ${products.length}`);
  for (const p of products.slice(0, 10)) {
    console.log(`    id=${p.id} number="${p.number}" name="${p.name}"`);
  }

  // Simulate filtering for specific product numbers
  const targetNumbers = ["PROD-001", "PROD-002"];
  const found = products.filter((p: any) => targetNumbers.includes(p.number));
  console.log(`  Found ${found.length} of ${targetNumbers.length} target products`);

  // TEST 2: Full optimized Task 10 flow simulation (5 calls)
  console.log("\n--- TEST 2: Full optimized flow (5 calls) ---");
  let callCount = 0;

  // Step 1: Parallel GETs (3 calls instead of 5)
  const custR = await api("GET", "/customer", undefined, { fields: "id,name", count: "1" });
  callCount++;
  const prodsR = await api("GET", "/product", undefined, { fields: "id,name,number", count: "100" });
  callCount++;
  const payR = await api("GET", "/invoice/paymentType", undefined, { fields: "id,description" });
  callCount++;

  const custId = custR.data.values?.[0]?.id;
  const allProducts = prodsR.data.values || [];
  const betaltId = payR.data.values?.find((p: any) => p.description === "Betalt til bank")?.id;

  // Pick any 2 products
  const prod1 = allProducts[0];
  const prod2 = allProducts.length > 1 ? allProducts[1] : allProducts[0];
  console.log(`  Customer: ${custId}, Products: ${prod1?.id}(${prod1?.number}), ${prod2?.id}(${prod2?.number})`);

  // Step 2: Create invoice with inline order+orderlines (1 call)
  const today = new Date().toISOString().split("T")[0];
  const dueDate = new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0];
  const inv = await api("POST", "/invoice", {
    invoiceDate: today,
    invoiceDueDate: dueDate,
    orders: [{
      customer: { id: custId },
      orderDate: today,
      deliveryDate: today,
      orderLines: [
        { product: { id: prod1.id }, count: 1, unitPriceExcludingVatCurrency: 1000, vatType: { id: 3 } },
        { product: { id: prod2.id }, count: 1, unitPriceExcludingVatCurrency: 2000, vatType: { id: 3 } },
      ],
    }],
  }, { sendToCustomer: "true" });
  callCount++;

  const invoiceId = inv.data.value?.id;
  const invoiceAmount = inv.data.value?.amount;
  console.log(`  Invoice: id=${invoiceId} amount=${invoiceAmount}`);

  // Step 3: Register payment (1 call)
  if (invoiceId && betaltId) {
    const pay = await api("PUT", `/invoice/${invoiceId}/:payment`, {}, {
      paymentDate: today,
      paymentTypeId: String(betaltId),
      paidAmount: String(invoiceAmount),
    });
    callCount++;
    console.log(`  Payment: status=${pay.status} outstanding=${pay.data.value?.amountOutstanding}`);
  }

  console.log(`\n  TOTAL API CALLS: ${callCount} (current: 7, saved: ${7 - callCount})`);

  // Compare with known efficiency scores
  console.log("\n=== EFFICIENCY ANALYSIS ===");
  console.log("Task 14: 3 calls → eff 2.0 (score 4.0)");
  console.log("Task 14: 6 calls → eff 2.0 (score 4.0)");
  console.log("Task 11: 5 calls → eff 2.0 (score 4.0)");
  console.log("Task 10: 7 calls → eff 1.5 (score 3.0)");
  console.log(`Task 10: ${callCount} calls → eff ??? (target: 2.0 for score 4.0)`);
}

main().catch(console.error);
