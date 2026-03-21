#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 12: Full payroll with finalization test ===\n");

  // Step 1: Find an employee with employment
  console.log("--- Step 1: Find employee + salary types ---");
  const [employees, type2000, type2002] = await Promise.all([
    client.get("/employee", { fields: "id,firstName,lastName,dateOfBirth,bankAccountNumber,email", count: "5" }),
    client.get("/salary/type", { number: "2000", fields: "id,number,name" }),
    client.get("/salary/type", { number: "2002", fields: "id,number,name" }),
  ]);

  const emp = employees.values?.[0];
  console.log(`  Employee: ${emp?.firstName} ${emp?.lastName} (${emp?.id}), dob=${emp?.dateOfBirth}, bank=${emp?.bankAccountNumber}`);
  console.log(`  Fastlønn: ${type2000.values?.[0]?.id}`);
  console.log(`  Bonus: ${type2002.values?.[0]?.id}`);

  // Step 2: Check employment
  console.log("\n--- Step 2: Check employment ---");
  const employment = await client.get("/employee/employment", {
    employeeId: String(emp.id), fields: "id,startDate,division(id,name)"
  });
  console.log(`  Employments: ${employment.values?.length}`);
  if (employment.values?.length > 0) {
    console.log(`  First: id=${employment.values[0].id}, start=${employment.values[0].startDate}, div=${employment.values[0].division?.name}`);
  }

  // Step 3: Ensure employee has bankAccountNumber and dateOfBirth
  if (!emp.bankAccountNumber || !emp.dateOfBirth) {
    console.log("\n--- Step 3: Update employee with missing fields ---");
    const fullEmp = await client.get(`/employee/${emp.id}`, { fields: "*" });
    const updated = await client.put(`/employee/${emp.id}`, {
      id: emp.id,
      version: fullEmp.value.version,
      firstName: emp.firstName,
      lastName: emp.lastName,
      dateOfBirth: emp.dateOfBirth || "1990-01-01",
      bankAccountNumber: emp.bankAccountNumber || "12345678903",
      email: emp.email || "test@example.org",
    });
    console.log(`  Updated: dob=${updated.value?.dateOfBirth}, bank=${updated.value?.bankAccountNumber}`);
  }

  // Step 4: Create salary transaction
  console.log("\n--- Step 4: Create salary transaction ---");
  const tx = await client.post("/salary/transaction", {
    date: "2026-03-21",
    year: 2026,
    month: 3,
    isHistorical: false,
    payslips: [{
      employee: { id: emp.id },
      date: "2026-03-21",
      year: 2026,
      month: 3,
      specifications: [
        { salaryType: { id: type2000.values[0].id }, rate: 33000, count: 1, amount: 33000, year: 2026, month: 3, employee: { id: emp.id } },
        { salaryType: { id: type2002.values[0].id }, rate: 17850, count: 1, amount: 17850, year: 2026, month: 3, employee: { id: emp.id } },
      ]
    }]
  }, { generateTaxDeduction: "true" });

  const txId = tx.value?.id;
  console.log(`  Transaction created: id=${txId}, version=${tx.value?.version}`);
  console.log(`  Payslips: ${tx.value?.payslips?.length}`);

  if (!txId) {
    console.log("  FAILED to create transaction:", JSON.stringify(tx));
    return;
  }

  // Step 5: Get payment type out
  console.log("\n--- Step 5: Get payment type out ---");
  const paymentTypes = await client.get("/ledger/paymentTypeOut", { fields: "id,description" });
  console.log("  Payment types out:");
  for (const pt of paymentTypes.values || []) {
    console.log(`    ${pt.id}: ${pt.description}`);
  }
  const paymentTypeId = paymentTypes.values?.[0]?.id;

  // Step 6: Try finalization via /tsk/ endpoint
  console.log("\n--- Step 6: Try /tsk/ finalization ---");
  const today = "2026-03-21";

  // Try the /tsk/ path
  console.log("  Trying PUT /tsk/salaryv2/transaction/:run ...");
  try {
    const result = await client.put(
      `/tsk/salaryv2/transaction/${txId}/:run`,
      {},
      { paymentTypeId: String(paymentTypeId), paymentDate: today, paySlipsAvailableDate: today, oneTimePassword: "" }
    );
    console.log("  Result:", JSON.stringify(result).slice(0, 500));
  } catch (e: any) {
    console.log("  Error:", e.message);
  }

  // Step 7: Check if transaction is finalized
  console.log("\n--- Step 7: Check transaction state ---");
  const txAfter = await client.get(`/salary/transaction/${txId}`, { fields: "*" });
  console.log(`  Transaction: id=${txAfter.value?.id}, version=${txAfter.value?.version}`);
  console.log(`  Full:`, JSON.stringify(txAfter.value).slice(0, 500));

  // Step 8: Check vouchers created
  console.log("\n--- Step 8: Check for Lønnsbilag voucher ---");
  const vouchers = await client.get("/ledger/voucher", {
    dateFrom: "2026-03-01", dateTo: "2026-03-31",
    fields: "id,number,date,description",
    count: "20"
  });
  for (const v of vouchers.values || []) {
    if (v.description?.includes("Lønn") || v.number >= 500000) {
      console.log(`  Voucher #${v.number}: ${v.description} (${v.date})`);
    }
  }
}

main().catch(console.error);
