#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 25: Test if product account field controls invoice posting ===\n");

  // Step 1: Get accounts 1500, 3400, 3000, and payment type
  console.log("--- Step 1: Get accounts ---");
  const [acc1500, acc3400, acc3000, acc1920, payTypes] = await Promise.all([
    client.get("/ledger/account", { number: "1500", fields: "id,number,name" }),
    client.get("/ledger/account", { number: "3400", fields: "id,number,name" }),
    client.get("/ledger/account", { number: "3000", fields: "id,number,name" }),
    client.get("/ledger/account", { number: "1920", fields: "id,number,name,bankAccountNumber,version" }),
    client.get("/invoice/paymentType", { fields: "id,description" }),
  ]);

  const id1500 = acc1500.values?.[0]?.id;
  const id3400 = acc3400.values?.[0]?.id;
  const id3000 = acc3000.values?.[0]?.id;
  const bank = acc1920.values?.[0];
  console.log(`  1500: ${id1500}`);
  console.log(`  3400: ${id3400}`);
  console.log(`  3000: ${id3000}`);
  console.log(`  1920: ${bank?.id} bankAccountNumber=${bank?.bankAccountNumber}`);
  console.log(`  Payment types:`, payTypes.values?.map((p: any) => `${p.id}: ${p.description}`));

  // Step 2: Ensure bank account has number
  if (bank && !bank.bankAccountNumber) {
    console.log("\n--- Setting bank account number ---");
    await client.put(`/ledger/account/${bank.id}`, {
      id: bank.id, version: bank.version, number: 1920, name: bank.name,
      bankAccountNumber: "12345678903"
    });
  }

  // Step 3: Find or create a customer
  console.log("\n--- Step 3: Find/create customer ---");
  let customers = await client.get("/customer", { fields: "id,name", count: "1" });
  let customerId: number;
  if (customers.values?.length > 0) {
    customerId = customers.values[0].id;
    console.log(`  Using existing customer: ${customers.values[0].name} (${customerId})`);
  } else {
    const cust = await client.post("/customer", { name: "Test Kunde AS", email: "test@example.org" });
    customerId = cust.value.id;
    console.log(`  Created customer: ${customerId}`);
  }

  // Step 4: Create product WITH account set to 3400
  console.log("\n--- Step 4: Create product with account=3400 ---");
  const product = await client.post("/product", {
    name: "Purregebyr",
    number: 9999,
    priceExcludingVatCurrency: 55,
    vatType: { id: 3 },
    account: { id: id3400 }
  });
  console.log(`  Product created: id=${product.value?.id}, account=${JSON.stringify(product.value?.account)}`);
  const productId = product.value?.id;

  // Step 5: Create order + orderline + invoice
  console.log("\n--- Step 5: Create order → orderline → invoice ---");
  const order = await client.post("/order", {
    customer: { id: customerId },
    orderDate: "2026-03-21",
    deliveryDate: "2026-03-21"
  });
  const orderId = order.value?.id;
  console.log(`  Order: ${orderId}`);

  const orderline = await client.post("/order/orderline", {
    order: { id: orderId },
    product: { id: productId },
    count: 1,
    unitPriceExcludingVatCurrency: 55,
    vatType: { id: 3 }
  });
  console.log(`  Orderline: ${orderline.value?.id}`);

  const invoice = await client.post("/invoice", {
    invoiceDate: "2026-03-21",
    invoiceDueDate: "2026-04-04",
    orders: [{ id: orderId }]
  }, { sendToCustomer: "true" });
  const invoiceId = invoice.value?.id;
  console.log(`  Invoice: ${invoiceId}`);

  // Step 6: Check what accounts the invoice posted to
  console.log("\n--- Step 6: Check invoice postings ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2026-03-20", dateTo: "2026-03-22",
    fields: "id,number,date,description",
    count: "50"
  });

  for (const v of vouchers.values || []) {
    console.log(`\n  Voucher #${v.number}: ${v.description}`);
    const postings = await client.get("/ledger/posting", {
      voucherId: String(v.id),
      fields: "id,account(id,number,name),amount,amountGross"
    });
    for (const p of postings.values || []) {
      console.log(`    ${p.account.number} (${p.account.name}): amount=${p.amount} gross=${p.amountGross}`);
    }
  }

  console.log("\n=== KEY QUESTION: Does the invoice credit 3400 or 3000? ===");
  console.log("If 3400 → we can skip the manual voucher (5 writes)");
  console.log("If 3000 → we still need the voucher (6 writes)");
}

main().catch(console.error);
