#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 30: Simplified year-end closing (årsoppgjør) ===\n");

  // Task: 3 assets depreciated linearly over 3 years
  // Programvare: 288400/3 = 96133.33 on account 1250, depreciation 6010, accum 1209
  // Kjøretøy: 120750/3 = 40250 on account 1230, depreciation 6010, accum 1209
  // IT-utstyr: 74550/3 = 24850 on account 1210, depreciation 6010, accum 1209
  // Reverse prepaid: 27350 from 1700
  // Tax: 22% of taxable result on 8700/2920

  // Step 1: Check which accounts exist
  console.log("--- Step 1: Check accounts ---");
  const accountNums = [1209, 1210, 1230, 1250, 1700, 2500, 2510, 2920, 6000, 6010, 6020, 6300, 8300, 8700];
  const results = await Promise.all(
    accountNums.map(n => client.get("/ledger/account", { number: String(n), fields: "id,number,name" }))
  );
  for (let i = 0; i < accountNums.length; i++) {
    const vals = results[i].values || [];
    console.log(`  ${accountNums[i]}: ${vals.length > 0 ? `${vals[0].id} - ${vals[0].name}` : 'NOT FOUND'}`);
  }

  // Step 2: Check existing ledger postings for P&L
  console.log("\n--- Step 2: Existing P&L postings (accounts 3000-8699) ---");
  const postings = await client.get("/ledger/posting", {
    dateFrom: "2025-01-01", dateTo: "2025-12-31",
    accountNumberFrom: "3000", accountNumberTo: "8699",
    count: "1000",
    fields: "id,account(id,number,name),amount"
  });

  // Aggregate by account
  const byAccount: Record<string, { name: string; total: number; count: number }> = {};
  for (const p of postings.values || []) {
    const key = String(p.account.number);
    if (!byAccount[key]) byAccount[key] = { name: p.account.name, total: 0, count: 0 };
    byAccount[key].total += p.amount;
    byAccount[key].count++;
  }

  let totalResult = 0;
  for (const [num, data] of Object.entries(byAccount).sort((a, b) => Number(a[0]) - Number(b[0]))) {
    console.log(`  ${num} (${data.name}): ${data.count} postings, total = ${data.total.toFixed(2)}`);
    totalResult += data.total;
  }
  console.log(`\n  Total P&L before adjustments: ${totalResult.toFixed(2)}`);

  // Step 3: Calculate depreciation
  console.log("\n--- Step 3: Depreciation calculations ---");
  const depProgramvare = Math.round(288400 / 3 * 100) / 100;
  const depKjoretoy = Math.round(120750 / 3 * 100) / 100;
  const depIT = Math.round(74550 / 3 * 100) / 100;
  const totalDep = depProgramvare + depKjoretoy + depIT;
  console.log(`  Programvare: 288400/3 = ${depProgramvare}`);
  console.log(`  Kjøretøy: 120750/3 = ${depKjoretoy}`);
  console.log(`  IT-utstyr: 74550/3 = ${depIT}`);
  console.log(`  Total depreciation: ${totalDep}`);

  // Step 4: Calculate adjusted result and tax
  const prepaidReversal = 27350;
  const adjustedResult = totalResult + totalDep + prepaidReversal;
  // Result is negative = profit (revenue is negative in Norwegian accounting)
  // If result is negative (profit), tax = 22% of |result|
  // If result is positive (loss), no tax
  console.log(`\n--- Step 4: Tax calculation ---`);
  console.log(`  Total P&L before adjustments: ${totalResult.toFixed(2)}`);
  console.log(`  + Depreciation: ${totalDep.toFixed(2)}`);
  console.log(`  + Prepaid reversal: ${prepaidReversal}`);
  console.log(`  = Adjusted result: ${adjustedResult.toFixed(2)}`);

  // In Tripletex: revenue is NEGATIVE (credit), expenses are POSITIVE (debit)
  // So negative result = profit
  const taxableProfit = -adjustedResult; // flip sign: positive = profit
  const tax = taxableProfit > 0 ? Math.round(taxableProfit * 0.22 * 100) / 100 : 0;
  console.log(`  Taxable profit: ${taxableProfit.toFixed(2)}`);
  console.log(`  Tax (22%): ${tax.toFixed(2)}`);

  // Step 5: Check what the agent actually posted
  console.log("\n--- Step 5: Check existing vouchers for 2025-12-31 ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2025-12-31", dateTo: "2025-12-31",
    fields: "id,number,date,description",
    count: "50"
  });
  for (const v of vouchers.values || []) {
    console.log(`  Voucher #${v.number}: ${v.description}`);
    // Get postings for this voucher
    const vPostings = await client.get("/ledger/posting", {
      voucherId: String(v.id),
      fields: "id,account(id,number,name),amount,amountGross"
    });
    for (const p of vPostings.values || []) {
      console.log(`    ${p.account.number} (${p.account.name}): amount=${p.amount} gross=${p.amountGross}`);
    }
  }

  // Step 6: Try posting a test voucher to see what accounts work
  // (Commenting out actual writes - uncomment to test)
  /*
  console.log("\n--- Step 6: Test voucher post ---");
  // Create accounts 1209 and 8700 if they don't exist
  const acc1209 = await client.post("/ledger/account", { number: 1209, name: "Akkumulerte avskrivninger" });
  console.log("Created 1209:", acc1209.value?.id || acc1209);

  const acc8700 = await client.post("/ledger/account", { number: 8700, name: "Skattekostnad" });
  console.log("Created 8700:", acc8700.value?.id || acc8700);
  */

  console.log("\n=== Summary ===");
  console.log(`Depreciation amounts: Programvare=${depProgramvare}, Kjøretøy=${depKjoretoy}, IT=${depIT}`);
  console.log(`Prepaid reversal: ${prepaidReversal}`);
  console.log(`Tax: ${tax}`);
  console.log(`Total write calls needed: 2 (create accounts) + 5 (vouchers) = 7`);
}

main().catch(console.error);
