#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 23: Bank reconciliation - match CSV to invoices ===\n");

  // The CSV data from the task:
  // Customer payments (Inn):
  //   2026-01-17 Lunde AS / Faktura 1001  9437.50
  //   2026-01-19 Neset AS / Faktura 1002  8187.50
  //   2026-01-21 Kvamme AS / Faktura 1003 15750.00
  //   2026-01-22 Stølsvik AS / Faktura 1004 7375.00
  //   2026-01-25 Stølsvik AS / Faktura 1005 11050.00
  // Supplier payments (Ut):
  //   2026-01-27 Brekke AS   -6100.00
  //   2026-01-30 Kvamme AS   -18400.00
  //   2026-01-31 Vik AS      -12300.00
  // Other:
  //   2026-02-02 Bankgebyr    -967.04
  //   2026-02-03 Bankgebyr    1097.62

  // Step 1: Check what invoices exist
  console.log("--- Step 1: Customer invoices ---");
  const invoices = await client.get("/invoice", {
    invoiceDateFrom: "2020-01-01", invoiceDateTo: "2026-12-31",
    fields: "id,invoiceNumber,customer(id,name),amount,amountOutstanding",
    count: "100"
  });
  console.log("Customer invoices:");
  for (const inv of invoices.values || []) {
    console.log(`  #${inv.invoiceNumber} ${inv.customer?.name} amount=${inv.amount} outstanding=${inv.amountOutstanding}`);
  }

  // Step 2: Check payment types
  console.log("\n--- Step 2: Payment types ---");
  const payTypes = await client.get("/invoice/paymentType", { fields: "id,description" });
  console.log("Payment types:", payTypes.values?.map((p: any) => `${p.id}: ${p.description}`));

  // Step 3: Check supplier invoices / vouchers with supplier postings
  console.log("\n--- Step 3: Supplier vouchers (leverandørgjeld) ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2020-01-01", dateTo: "2026-12-31",
    fields: "id,number,date,description",
    count: "50"
  });
  console.log("Vouchers:");
  for (const v of vouchers.values || []) {
    console.log(`  #${v.number} ${v.date} ${v.description}`);
  }

  // Step 4: Check ledger postings on account 2400 (leverandørgjeld) for open supplier balances
  console.log("\n--- Step 4: Account 2400 postings (supplier payables) ---");
  const postings2400 = await client.get("/ledger/posting", {
    dateFrom: "2020-01-01", dateTo: "2026-12-31",
    accountNumberFrom: "2400", accountNumberTo: "2400",
    fields: "id,date,description,supplier(id,name),amount,invoiceNumber",
    count: "50"
  });
  console.log("Account 2400 postings:");
  for (const p of postings2400.values || []) {
    console.log(`  ${p.date} ${p.supplier?.name || 'no supplier'} amount=${p.amount} inv=${p.invoiceNumber} desc=${p.description}`);
  }

  // Step 5: Check if there's a bank reconciliation API
  console.log("\n--- Step 5: Bank reconciliation endpoints ---");
  const bankRecon = await client.get("/bank/reconciliation", { count: "5" });
  console.log("Bank reconciliation:", JSON.stringify(bankRecon, null, 2).slice(0, 500));

  // Step 6: Check bank statements
  console.log("\n--- Step 6: Bank statements ---");
  const bankStmt = await client.get("/bank/statement", { count: "5" });
  console.log("Bank statements:", JSON.stringify(bankStmt, null, 2).slice(0, 500));

  // Step 7: How should supplier payments be registered?
  // Option A: via voucher (debit 2400, credit 1920)
  // Option B: via some supplier payment endpoint
  console.log("\n--- Step 7: Check supplierInvoice endpoint ---");
  const suppInv = await client.get("/supplierInvoice", {
    invoiceDateFrom: "2020-01-01", invoiceDateTo: "2026-12-31",
    fields: "id,invoiceNumber,supplier(id,name),amount",
    count: "20"
  });
  console.log("Supplier invoices:", JSON.stringify(suppInv, null, 2).slice(0, 500));

  // Step 8: Check incomingInvoice
  console.log("\n--- Step 8: Check incomingInvoice endpoint ---");
  const incoming = await client.get("/incomingInvoice", {
    invoiceDateFrom: "2020-01-01", invoiceDateTo: "2026-12-31",
    count: "20"
  });
  console.log("Incoming invoices:", JSON.stringify(incoming, null, 2).slice(0, 500));

  console.log("\n--- API call log ---");
  console.log(client.callLog.map(c => `${c.method} ${c.path} → ${c.status}`));
}

main().catch(console.error);
