#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 12: Payroll with bonus ===\n");

  // Step 1: Get salary types
  console.log("--- Step 1: Salary types 2000 and 2002 ---");
  const [type2000, type2002] = await Promise.all([
    client.get("/salary/type", { number: "2000", fields: "id,number,name" }),
    client.get("/salary/type", { number: "2002", fields: "id,number,name" })
  ]);
  const type2000Id = type2000.values?.[0]?.id;
  const type2002Id = type2002.values?.[0]?.id;
  console.log("2000 Fastlønn id:", type2000Id);
  console.log("2002 Bonus id:", type2002Id);

  // Step 2: Use first employee with employment
  console.log("\n--- Step 2: Find employee with employment ---");
  const emp = await client.get("/employee", { fields: "id,firstName,lastName,dateOfBirth", count: "1" });
  const empId = emp.values?.[0]?.id;
  console.log("Employee:", emp.values?.[0]);

  const employment = await client.get("/employee/employment", { employeeId: String(empId), fields: "id,startDate,division" });
  console.log("Employment:", employment.values?.[0] ? "exists" : "MISSING");
  if (!employment.values?.length) { console.log("No employment, can't test"); return; }

  // Step 3: Create salary transaction
  console.log("\n--- Step 3: POST salary transaction ---");
  const tx = await client.post("/salary/transaction", {
    date: "2026-03-21",
    year: 2026,
    month: 5,
    isHistorical: false,
    payslips: [{
      employee: { id: empId },
      date: "2026-03-21",
      year: 2026,
      month: 5,
      specifications: [
        { salaryType: { id: type2000Id }, rate: 33000, count: 1, amount: 33000, year: 2026, month: 5, employee: { id: empId } },
        { salaryType: { id: type2002Id }, rate: 17850, count: 1, amount: 17850, year: 2026, month: 5, employee: { id: empId } }
      ]
    }]
  }, { generateTaxDeduction: "true" });
  console.log("Transaction ID:", tx.value?.id);

  if (!tx.value?.id) { console.log("FAILED:", JSON.stringify(tx, null, 2)); return; }

  // Step 4: VALIDATE - read back everything
  console.log("\n--- Step 4: VALIDATE - Read back payslip ---");
  const payslipId = tx.value.payslips?.[0]?.id;
  const payslip = await client.get(`/salary/payslip/${payslipId}`, { fields: "*" });
  const ps = payslip.value;
  console.log("Payslip grossAmount:", ps?.grossAmount);
  console.log("Payslip amount (net):", ps?.amount);
  console.log("Payslip vacationAllowance:", ps?.vacationAllowanceAmount);
  console.log("Payslip specs count:", ps?.specifications?.length);

  // Step 5: Read each specification
  console.log("\n--- Step 5: VALIDATE - Read specifications ---");
  for (const spec of ps?.specifications || []) {
    const s = await client.get(`/salary/specification/${spec.id}`, { fields: "*" });
    const v = s.value;
    console.log(`  Spec ${v?.id}: type=${v?.salaryType?.number || v?.salaryType?.id} rate=${v?.rate} count=${v?.count} amount=${v?.amount} desc=${v?.description}`);
  }

  // Step 6: Check the voucher/ledger postings created by the salary transaction
  console.log("\n--- Step 6: VALIDATE - Check salary vouchers ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2026-03-21", dateTo: "2026-03-21",
    fields: "id,number,date,description",
    count: "20"
  });
  console.log("Vouchers on 2026-03-21:");
  for (const v of vouchers.values || []) {
    console.log(`  Voucher ${v.id}: #${v.number} ${v.description}`);
  }

  // Step 7: Check the salary transaction itself
  console.log("\n--- Step 7: VALIDATE - Read transaction back ---");
  const txBack = await client.get(`/salary/transaction/${tx.value.id}`, { fields: "*" });
  console.log("Transaction:", JSON.stringify(txBack.value, null, 2));

  // Step 8: Check if employee now has salary data
  console.log("\n--- Step 8: VALIDATE - Employee salary overview ---");
  const empFull = await client.get(`/employee/${empId}`, { fields: "*" });
  console.log("Employee dateOfBirth:", empFull.value?.dateOfBirth);
  console.log("Employee employments:", empFull.value?.employments?.length);

  console.log("\n--- API call log ---");
  console.log(client.callLog.map(c => `${c.method} ${c.path} → ${c.status}`));
}

main().catch(console.error);
