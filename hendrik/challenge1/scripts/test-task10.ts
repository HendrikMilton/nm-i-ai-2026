#!/usr/bin/env bun
/**
 * Task 10 efficiency test: Can we reduce API calls below 7?
 * Current: 7 calls (5 GET + 2 write). All checks pass.
 *
 * Optimizations to test:
 * 1. Skip GET /ledger/account?number=1920 (never used)
 * 2. Reference product by number instead of id in orderLine
 * 3. Reference customer by organizationNumber instead of id
 * 4. Skip GET /invoice/paymentType somehow
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
  console.log("=== TASK 10 OPTIMIZATION TESTS ===\n");

  // Get baseline data
  const custR = await api("GET", "/customer", undefined, { fields: "id,name,organizationNumber", count: "1" });
  const cust = custR.data.values?.[0];
  console.log(`Customer: id=${cust?.id} name=${cust?.name} orgNr=${cust?.organizationNumber}`);

  const prodR = await api("GET", "/product", undefined, { fields: "id,name,number", count: "2" });
  const products = prodR.data.values || [];
  console.log(`Products: ${products.map((p: any) => `id=${p.id} num=${p.number} name=${p.name}`).join(", ")}`);

  const payR = await api("GET", "/invoice/paymentType", undefined, { fields: "id,description" });
  const betaltId = payR.data.values?.find((p: any) => p.description === "Betalt til bank")?.id;
  console.log(`"Betalt til bank" id: ${betaltId}\n`);

  const today = new Date().toISOString().split("T")[0];
  const dueDate = new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0];

  // TEST 1: Can we reference product by NUMBER in orderLine?
  console.log("=== TEST 1: orderLine with product:{number} instead of product:{id} ===");
  if (products.length >= 1) {
    const inv1 = await api("POST", "/invoice", {
      invoiceDate: today,
      invoiceDueDate: dueDate,
      orders: [{
        customer: { id: cust.id },
        orderDate: today,
        deliveryDate: today,
        orderLines: [{
          product: { number: products[0].number },  // number instead of id
          count: 1,
          unitPriceExcludingVatCurrency: 100,
          vatType: { id: 3 },
        }],
      }],
    }, { sendToCustomer: "true" });

    if (inv1.status === 201) {
      console.log(`  SUCCESS! Product referenced by number works`);
      console.log(`  Invoice amount: ${inv1.data.value?.amount}`);
    } else {
      console.log(`  FAILED — need product id`);
    }
  }

  // TEST 2: Can we reference customer by organizationNumber?
  console.log("\n=== TEST 2: order with customer:{organizationNumber} instead of customer:{id} ===");
  if (products.length >= 1) {
    const inv2 = await api("POST", "/invoice", {
      invoiceDate: today,
      invoiceDueDate: dueDate,
      orders: [{
        customer: { organizationNumber: cust.organizationNumber },
        orderDate: today,
        deliveryDate: today,
        orderLines: [{
          product: { id: products[0].id },
          count: 1,
          unitPriceExcludingVatCurrency: 100,
          vatType: { id: 3 },
        }],
      }],
    }, { sendToCustomer: "true" });

    if (inv2.status === 201) {
      console.log(`  SUCCESS! Customer referenced by orgNumber works`);
    } else {
      console.log(`  FAILED — need customer id`);
    }
  }

  // TEST 3: Both product number + customer orgNumber together
  console.log("\n=== TEST 3: Both product:{number} + customer:{organizationNumber} ===");
  if (products.length >= 1 && cust.organizationNumber) {
    const inv3 = await api("POST", "/invoice", {
      invoiceDate: today,
      invoiceDueDate: dueDate,
      orders: [{
        customer: { organizationNumber: cust.organizationNumber },
        orderDate: today,
        deliveryDate: today,
        orderLines: [{
          product: { number: products[0].number },
          count: 1,
          unitPriceExcludingVatCurrency: 100,
          vatType: { id: 3 },
        }],
      }],
    }, { sendToCustomer: "true" });

    if (inv3.status === 201) {
      console.log(`  SUCCESS! Both work — can skip GET /customer AND GET /product`);
      console.log(`  Invoice amount: ${inv3.data.value?.amount}`);
    } else {
      console.log(`  FAILED`);
    }
  }

  // TEST 4: Can we register payment without paymentTypeId?
  console.log("\n=== TEST 4: Payment without paymentTypeId ===");
  // First create a valid invoice
  const inv4 = await api("POST", "/invoice", {
    invoiceDate: today,
    invoiceDueDate: dueDate,
    orders: [{
      customer: { id: cust.id },
      orderDate: today,
      deliveryDate: today,
      orderLines: [{
        product: { id: products[0].id },
        count: 1,
        unitPriceExcludingVatCurrency: 100,
        vatType: { id: 3 },
      }],
    }],
  }, { sendToCustomer: "true" });
  const inv4Id = inv4.data.value?.id;
  const inv4Amount = inv4.data.value?.amount;

  if (inv4Id) {
    // Try with paymentTypeId=0
    console.log("  Trying paymentTypeId=0...");
    const pay4a = await api("PUT", `/invoice/${inv4Id}/:payment`, {}, {
      paymentDate: today,
      paymentTypeId: "0",
      paidAmount: String(inv4Amount),
    });
    if (pay4a.status === 200) {
      console.log(`  SUCCESS with paymentTypeId=0!`);
    } else {
      // Try without paymentTypeId at all
      console.log("  Trying without paymentTypeId...");
      const pay4b = await api("PUT", `/invoice/${inv4Id}/:payment`, {}, {
        paymentDate: today,
        paidAmount: String(inv4Amount),
      });
      if (pay4b.status === 200) {
        console.log(`  SUCCESS without paymentTypeId!`);
      } else {
        console.log(`  FAILED — paymentTypeId required`);
      }
    }
  }

  // SUMMARY
  console.log("\n=== SUMMARY ===");
  const results = {
    productByNumber: false,
    customerByOrgNr: false,
    skipPaymentType: false,
  };
  // Re-check from outputs above... let me just print what we know
  console.log("Results will show above. Check each test status.");
  console.log("\nCurrent: 7 API calls");
  console.log("Potential minimum depends on test results above.");
}

main().catch(console.error);
