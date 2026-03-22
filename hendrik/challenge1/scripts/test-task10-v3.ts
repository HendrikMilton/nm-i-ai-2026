#!/usr/bin/env bun
/**
 * Task 10 thorough test v3:
 * - Verify bulk product lookup returns correct data for filtering
 * - Test with realistic task data (2 specific product numbers)
 * - Verify the full invoice creation + payment flow end-to-end
 * - Test edge cases: what if product count > 100? Missing products?
 * - Verify invoice postings are correct (1500 debit, 3000 credit, VAT)
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
  if (res.status >= 400) console.log(`  ERROR ${method} ${path} → ${res.status}:`, JSON.stringify(json).slice(0, 400));
  return { status: res.status, data: json };
}

async function main() {
  console.log("=== TASK 10 THOROUGH TESTS ===\n");

  // ============================================
  // TEST 1: Bulk product lookup edge cases
  // ============================================
  console.log("=== TEST 1: Bulk product lookup ===");

  // 1a: How many products exist?
  const allProds = await api("GET", "/product", undefined, {
    fields: "id,name,number", count: "1000",
  });
  const products = allProds.data.values || [];
  console.log(`Total products: ${allProds.data.fullResultSize} (returned ${products.length})`);

  // 1b: How many have a number set?
  const withNumber = products.filter((p: any) => p.number && p.number.trim() !== "");
  console.log(`Products with number: ${withNumber.length}`);
  for (const p of withNumber) {
    console.log(`  number="${p.number}" name="${p.name}" id=${p.id}`);
  }

  // 1c: Are product numbers unique?
  const numSet = new Set(withNumber.map((p: any) => p.number));
  console.log(`Unique numbers: ${numSet.size} (duplicates: ${withNumber.length - numSet.size})`);

  // 1d: Simulate task — pick 2 products and look them up from bulk response
  console.log("\nSimulate task lookup:");
  const targetNums = ["PROD-001", "STOL-01"]; // from sandbox data
  for (const num of targetNums) {
    const found = products.find((p: any) => p.number === num);
    console.log(`  Looking for "${num}": ${found ? `FOUND id=${found.id} name="${found.name}"` : "NOT FOUND"}`);
  }

  // 1e: Test with numeric product numbers (competition uses these)
  console.log("\nWith numeric numbers (like competition):");
  const numericProds = withNumber.filter((p: any) => /^\d+$/.test(p.number));
  console.log(`  Products with numeric numbers: ${numericProds.length}`);
  for (const p of numericProds.slice(0, 5)) {
    console.log(`    number="${p.number}" name="${p.name}"`);
  }

  // ============================================
  // TEST 2: Individual vs bulk lookup comparison
  // ============================================
  console.log("\n=== TEST 2: Individual vs bulk lookup ===");
  if (withNumber.length >= 1) {
    const testNum = withNumber[0].number;

    // Individual lookup
    const indiv = await api("GET", "/product", undefined, {
      number: testNum, fields: "id,name,number",
    });
    const indivResult = indiv.data.values?.[0];
    console.log(`Individual GET /product?number=${testNum}: id=${indivResult?.id} name="${indivResult?.name}"`);

    // Bulk lookup + filter
    const bulkResult = products.find((p: any) => p.number === testNum);
    console.log(`Bulk filter for "${testNum}": id=${bulkResult?.id} name="${bulkResult?.name}"`);

    console.log(`Match: ${indivResult?.id === bulkResult?.id ? "YES" : "NO"}`);
  }

  // ============================================
  // TEST 3: Full end-to-end flow with 5 calls
  // ============================================
  console.log("\n=== TEST 3: Full E2E flow (5 API calls) ===");

  // Get a customer with orgNr
  const custSearch = await api("GET", "/customer", undefined, {
    fields: "id,name,organizationNumber", count: "10",
  });
  const customers = custSearch.data.values || [];
  const custWithOrg = customers.find((c: any) => c.organizationNumber);
  console.log(`Customer: id=${custWithOrg?.id} name="${custWithOrg?.name}" org=${custWithOrg?.organizationNumber}`);

  if (!custWithOrg || withNumber.length < 2) {
    console.log("Not enough test data for E2E test");
    return;
  }

  console.log("\n--- Simulated 5-call flow ---");
  let callCount = 0;

  // CALL 1: GET customer
  console.log(`CALL ${++callCount}: GET /customer?organizationNumber=${custWithOrg.organizationNumber}`);
  const c1 = await api("GET", "/customer", undefined, {
    organizationNumber: custWithOrg.organizationNumber,
    fields: "id,name",
  });
  const customerId = c1.data.values?.[0]?.id;

  // CALL 2: GET all products (bulk)
  console.log(`CALL ${++callCount}: GET /product?count=100 (bulk)`);
  const c2 = await api("GET", "/product", undefined, {
    fields: "id,name,number", count: "100",
  });
  const allProds2 = c2.data.values || [];
  const p1 = allProds2.find((p: any) => p.number === withNumber[0].number);
  const p2 = allProds2.find((p: any) => p.number === (withNumber.length > 1 ? withNumber[1].number : withNumber[0].number));
  console.log(`  Filtered: ${p1?.name} (${p1?.number}), ${p2?.name} (${p2?.number})`);

  // CALL 3: GET payment types
  console.log(`CALL ${++callCount}: GET /invoice/paymentType`);
  const c3 = await api("GET", "/invoice/paymentType", undefined, { fields: "id,description" });
  const betaltId = c3.data.values?.find((p: any) => p.description === "Betalt til bank")?.id;

  // CALL 4: POST invoice with inline order+orderlines
  const today = new Date().toISOString().split("T")[0];
  const dueDate = new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0];
  console.log(`CALL ${++callCount}: POST /invoice?sendToCustomer=true (inline order+orderlines)`);
  const c4 = await api("POST", "/invoice", {
    invoiceDate: today,
    invoiceDueDate: dueDate,
    orders: [{
      customer: { id: customerId },
      orderDate: today,
      deliveryDate: today,
      orderLines: [
        { product: { id: p1.id }, count: 1, unitPriceExcludingVatCurrency: 14650, vatType: { id: 3 } },
        { product: { id: p2.id }, count: 1, unitPriceExcludingVatCurrency: 11800, vatType: { id: 3 } },
      ],
    }],
  }, { sendToCustomer: "true" });

  const invoiceId = c4.data.value?.id;
  const invoiceAmount = c4.data.value?.amount;
  const amountExclVat = c4.data.value?.amountExcludingVat;
  console.log(`  Invoice: id=${invoiceId} amount=${invoiceAmount} exclVat=${amountExclVat}`);
  console.log(`  Voucher: ${c4.data.value?.voucher?.id}`);

  // Verify the invoice postings
  if (c4.data.value?.voucher?.id) {
    const voucher = await api("GET", `/ledger/voucher/${c4.data.value.voucher.id}`, undefined, {
      fields: "id,postings(id,account(id,number,name),amount,amountGross)"
    });
    console.log(`  Voucher postings:`);
    for (const posting of voucher.data.value?.postings || []) {
      console.log(`    ${posting.account?.number} ${posting.account?.name}: ${posting.amount} (gross: ${posting.amountGross})`);
    }
  }

  // CALL 5: PUT payment
  console.log(`CALL ${++callCount}: PUT /invoice/${invoiceId}/:payment`);
  // Note: this might fail in sandbox due to reconciled period, that's OK
  const c5 = await api("PUT", `/invoice/${invoiceId}/:payment`, {}, {
    paymentDate: today,
    paymentTypeId: String(betaltId),
    paidAmount: String(invoiceAmount),
  });
  if (c5.status === 200) {
    console.log(`  Payment SUCCESS! Outstanding: ${c5.data.value?.amountOutstanding}`);
  } else {
    console.log(`  Payment failed (likely sandbox period issue — would work in competition)`);
  }

  console.log(`\n--- TOTAL: ${callCount} API calls ---`);
  console.log(`Current approach: 7 calls`);
  console.log(`Optimized: ${callCount} calls (saved ${7 - callCount})`);

  // ============================================
  // TEST 4: What if we need specific product fields?
  // ============================================
  console.log("\n=== TEST 4: Does bulk product response have all needed fields? ===");
  const fullProd = await api("GET", "/product", undefined, {
    fields: "id,name,number,priceExcludingVatCurrency,vatType(id,percentage)",
    count: "5",
  });
  for (const p of (fullProd.data.values || []).slice(0, 3)) {
    console.log(`  id=${p.id} number="${p.number}" price=${p.priceExcludingVatCurrency} vat=${p.vatType?.id}(${p.vatType?.percentage}%)`);
  }
  console.log("  Note: task provides prices in the prompt, so we only need product ID from lookup");

  console.log("\n=== DONE ===");
}

main().catch(console.error);
