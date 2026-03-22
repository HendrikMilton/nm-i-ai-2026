#!/usr/bin/env bun
/**
 * Task 25 efficiency test v2: Test the two key optimizations:
 * 1. Can we create product with account:{number:3400} (skip GET /ledger/account)?
 * 2. Can we use inline order+orderlines in POST /invoice (skip POST /order + POST /order/orderline)?
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
  console.log("=== TASK 25 OPTIMIZATION TESTS ===\n");

  // Get account 3400 ID for comparison
  const acctR = await api("GET", "/ledger/account", undefined, { number: "3400", fields: "id,number,name" });
  const acct3400Id = acctR.data.values?.[0]?.id;
  console.log(`Account 3400: id=${acct3400Id} name=${acctR.data.values?.[0]?.name}`);

  // Get a customer to use
  const custR = await api("GET", "/customer", undefined, { fields: "id,name", count: "1" });
  const custId = custR.data.values?.[0]?.id;
  console.log(`Customer: id=${custId} name=${custR.data.values?.[0]?.name}\n`);

  // TEST 1: Create product with account:{number:3400} instead of account:{id}
  console.log("=== TEST 1: Product with account:{number:3400} ===");
  const prod1 = await api("POST", "/product", {
    name: `T25_NumAcct_${Date.now()}`,
    number: 80000 + Math.floor(Math.random() * 10000),
    priceExcludingVatCurrency: 70,
    vatType: { id: 0 },
    account: { number: 3400 },
  });
  if (prod1.status === 201) {
    const acctInResp = prod1.data.value?.account;
    console.log(`  SUCCESS! account in response: id=${acctInResp?.id} number=${acctInResp?.number}`);
    console.log(`  Matches expected 3400 id? ${acctInResp?.id === acct3400Id}`);
  }

  // TEST 2: Create product with account:{id} (current approach)
  console.log("\n=== TEST 2: Product with account:{id} (current) ===");
  const prod2 = await api("POST", "/product", {
    name: `T25_IdAcct_${Date.now()}`,
    number: 80000 + Math.floor(Math.random() * 10000),
    priceExcludingVatCurrency: 70,
    vatType: { id: 0 },
    account: { id: acct3400Id },
  });
  if (prod2.status === 201) {
    console.log(`  SUCCESS! account: id=${prod2.data.value?.account?.id}`);
  }

  // Pick a working product
  const productId = (prod1.status === 201 ? prod1 : prod2).data.value?.id;

  // TEST 3: Inline order+orderlines in POST /invoice
  console.log("\n=== TEST 3: POST /invoice with INLINE order+orderlines ===");
  const today = new Date().toISOString().split("T")[0];
  const dueDate = new Date(Date.now() + 14 * 86400000).toISOString().split("T")[0];

  const inv3 = await api("POST", "/invoice", {
    invoiceDate: today,
    invoiceDueDate: dueDate,
    orders: [{
      customer: { id: custId },
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

  if (inv3.status === 201) {
    const v = inv3.data.value;
    console.log(`  SUCCESS! Invoice created`);
    console.log(`  id=${v?.id} number=${v?.invoiceNumber} amount=${v?.amount}`);
    console.log(`  amountExclVat=${v?.amountExcludingVat} outstanding=${v?.amountOutstanding}`);
    console.log(`  voucher: ${v?.voucher?.id}`);
    console.log(`  This replaced 3 calls (POST /order + POST /order/orderline + POST /invoice) with 1 call!`);
  }

  // TEST 4: Full optimized flow simulation (count API calls)
  console.log("\n=== TEST 4: Full optimized flow (counting calls) ===");
  let callCount = 0;

  // Step 1: Parallel GETs (3 calls, or 2 if account number works)
  const canSkipAcctLookup = prod1.status === 201;

  if (canSkipAcctLookup) {
    console.log("  [CALL 1] GET /invoice (find overdue)     } parallel");
    console.log("  [CALL 2] GET /invoice/paymentType         }");
    callCount = 2;
  } else {
    console.log("  [CALL 1] GET /invoice (find overdue)        }");
    console.log("  [CALL 2] GET /ledger/account?number=3400    } parallel");
    console.log("  [CALL 3] GET /invoice/paymentType            }");
    callCount = 3;
  }

  // Step 2: Create product
  callCount++;
  console.log(`  [CALL ${callCount}] POST /product (purregebyr, account 3400, vatType 0)`);

  // Step 3: Create invoice with inline order (1 call instead of 3)
  callCount++;
  console.log(`  [CALL ${callCount}] POST /invoice?sendToCustomer=true (INLINE order+orderlines)`);

  // Step 4: Register partial payment
  callCount++;
  console.log(`  [CALL ${callCount}] PUT /invoice/:payment (partial 5000)`);

  console.log(`\n  TOTAL: ${callCount} API calls (current best: 9, saved: ${9 - callCount})`);

  console.log("\n=== RESULTS ===");
  console.log(`Product with account:{number:3400}: ${prod1.status === 201 ? "WORKS" : "FAILS (need id lookup)"}`);
  console.log(`Inline order+orderlines:            ${inv3.status === 201 ? "WORKS" : "FAILS"}`);
  console.log(`Minimum API calls:                  ${callCount}`);
  console.log(`Current best:                       9`);
  console.log(`Calls saved:                        ${9 - callCount}`);
}

main().catch(console.error);
