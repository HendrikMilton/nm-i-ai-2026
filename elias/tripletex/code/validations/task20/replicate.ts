#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 20: Supplier invoice from PDF ===\n");

  // Step 1: Check if supplier exists
  console.log("--- Step 1: Find supplier ---");
  const sup = await client.get("/supplier", { organizationNumber: "849825054", fields: "id,name" });
  console.log("Supplier search:", JSON.stringify(sup, null, 2));

  // Step 2: Try creating supplier with bankAccounts (the format that failed)
  console.log("\n--- Step 2a: Create supplier WITH bankAccounts (agent's failed attempt) ---");
  const sup2a = await client.post("/supplier", {
    name: "Test20-BankAccounts",
    organizationNumber: "849825054",
    email: "test@example.org",
    invoiceEmail: "test@example.org",
    bankAccounts: [{ bankAccountNumber: "29125778494" }],
    postalAddress: { addressLine1: "Nygata 145", postalCode: "7010", city: "Trondheim" }
  });
  console.log("Result:", JSON.stringify(sup2a, null, 2));

  // Step 2b: Try with bankAccountNumber as direct field
  console.log("\n--- Step 2b: Create supplier with direct bankAccountNumber field ---");
  const sup2b = await client.post("/supplier", {
    name: "Test20-DirectBank",
    organizationNumber: "849825055",
    email: "test2@example.org",
    invoiceEmail: "test2@example.org",
    bankAccounts: [{ number: "29125778494" }],
    postalAddress: { addressLine1: "Nygata 145", postalCode: "7010", city: "Trondheim" }
  });
  console.log("Result:", JSON.stringify(sup2b, null, 2));

  // Step 2c: Try completely without bankAccounts, then check what fields supplier has
  console.log("\n--- Step 2c: Create supplier without bank, inspect fields ---");
  const sup2c = await client.post("/supplier", {
    name: "Test20-NoBank",
    organizationNumber: "849825056",
    email: "test3@example.org",
    invoiceEmail: "test3@example.org",
    postalAddress: { addressLine1: "Nygata 145", postalCode: "7010", city: "Trondheim" }
  });
  console.log("Result:", JSON.stringify(sup2c, null, 2));

  // Step 2d: If supplier created, GET it back with all fields to see bank account structure
  const supId = sup2c.value?.id;
  if (supId) {
    console.log("\n--- Step 2d: GET supplier with fields=* ---");
    const supFull = await client.get(`/supplier/${supId}`, { fields: "*" });
    console.log("Full supplier:", JSON.stringify(supFull.value, null, 2));

    // Step 2e: Try PUT to add bank account
    console.log("\n--- Step 2e: PUT supplier to add bankAccounts ---");
    const ver = supFull.value?.version;
    const supPut = await client.put(`/supplier/${supId}`, {
      id: supId,
      version: ver,
      name: "Test20-NoBank",
      bankAccounts: [{ bankAccountNumber: "29125778494" }]
    });
    console.log("PUT result:", JSON.stringify(supPut, null, 2));
  }

  // Step 3: Look up accounts
  console.log("\n--- Step 3: Accounts ---");
  const acc6300 = await client.get("/ledger/account", { number: "6300", fields: "id,number,name" });
  const acc2400 = await client.get("/ledger/account", { number: "2400", fields: "id,number,name" });
  console.log("6300:", JSON.stringify(acc6300.values?.[0], null, 2));
  console.log("2400:", JSON.stringify(acc2400.values?.[0], null, 2));

  // Step 4: Post voucher (using a test supplier)
  const testSupId = sup2c.value?.id;
  const expenseId = acc6300.values?.[0]?.id;
  const payableId = acc2400.values?.[0]?.id;

  if (testSupId && expenseId && payableId) {
    console.log("\n--- Step 4: Post voucher ---");
    const voucher = await client.post("/ledger/voucher", {
      date: "2026-03-06",
      description: "Vedlikeholdsavtale - Test20 INV-2026-8795",
      postings: [
        {
          date: "2026-03-06",
          description: "Vedlikeholdsavtale",
          account: { id: expenseId },
          supplier: { id: testSupId },
          amountGross: 84125,
          amountGrossCurrency: 84125,
          vatType: { id: 1 },
          invoiceNumber: "INV-2026-8795",
          row: 1
        },
        {
          date: "2026-03-06",
          description: "Vedlikeholdsavtale",
          account: { id: payableId },
          supplier: { id: testSupId },
          amountGross: -84125,
          amountGrossCurrency: -84125,
          row: 2
        }
      ]
    });
    console.log("Voucher:", JSON.stringify(voucher, null, 2));
  }

  console.log("\n--- API call log ---");
  console.log(client.callLog);
}

main().catch(console.error);
