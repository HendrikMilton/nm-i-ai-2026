#!/usr/bin/env bun
/**
 * Validate payroll: replicate the 06:05PM run (Gunnhild Aasen, 51800 base + 5700 bonus)
 * Creates unique data, runs payroll, then GET-validates everything.
 */
const BASE_URL = process.env.TRIPLETEX_SANDBOX_URL!;
const SESSION_TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
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
  if (res.status >= 400) console.log("  ERROR:", JSON.stringify(json).slice(0, 800));
  return { status: res.status, data: json };
}

async function main() {
  const uid = Date.now().toString(36);
  console.log(`\n=== PAYROLL VALIDATION (Gunnhild pattern) uid=${uid} ===\n`);

  // 1. Create a unique employee
  const dept = await api("GET", "/department", undefined, { fields: "id,name", count: "1" });
  const deptId = dept.data.values[0].id;

  const emp = await api("POST", "/employee", {
    firstName: `TestPayroll`,
    lastName: `V${uid}`,
    email: `payroll-${uid}@test.no`,
    dateOfBirth: "1990-01-01",
    department: { id: deptId },
    userType: "NO_ACCESS",
  });
  const employeeId = emp.data.value.id;
  const empVersion = emp.data.value.version;
  console.log(`  Employee created: ${employeeId}`);

  // 2. Create division if needed
  let divisionId: number;
  const divs = await api("GET", "/division", undefined, { fields: "id,name" });
  if (divs.data.values?.length > 0) {
    divisionId = divs.data.values[0].id;
    console.log(`  Using existing division: ${divisionId}`);
  } else {
    const muni = await api("GET", "/municipality", undefined, { fields: "id,name", count: "1" });
    const div = await api("POST", "/division", {
      name: "Test Division",
      organizationNumber: "999999999",
      startDate: "2026-01-01",
      municipalityDate: "2026-01-01",
      municipality: { id: muni.data.values[0].id },
    });
    divisionId = div.data.value.id;
    console.log(`  Division created: ${divisionId}`);
  }

  // 3. Create employment
  const employment = await api("POST", "/employee/employment", {
    employee: { id: employeeId },
    startDate: "2026-01-01",
    division: { id: divisionId },
    employmentId: "1",
    isMainEmployer: true,
    taxDeductionCode: "loennFraHovedarbeidsgiver",
    employmentDetails: [{
      date: "2026-01-01",
      employmentType: "ORDINARY",
      employmentForm: "PERMANENT",
      remunerationType: "MONTHLY_WAGE",
      workingHoursScheme: "NOT_SHIFT",
      percentageOfFullTimeEquivalent: 100,
      shiftDurationHours: 7.5,
    }],
  });
  console.log(`  Employment created: ${employment.data.value?.id}`);

  // 4. Get salary types
  const st2000 = await api("GET", "/salary/type", undefined, { number: "2000", fields: "id,number,name" });
  const st2002 = await api("GET", "/salary/type", undefined, { number: "2002", fields: "id,number,name" });
  const fastlonnId = st2000.data.values[0].id;
  const bonusId = st2002.data.values[0].id;
  console.log(`  Fastlonn type: ${fastlonnId}, Bonus type: ${bonusId}`);

  // 5. Create salary transaction (like the agent did)
  const today = "2026-03-20";
  const tx = await api("POST", "/salary/transaction", {
    date: today,
    year: 2026,
    month: 3,
    isHistorical: false,
    payslips: [{
      employee: { id: employeeId },
      date: today,
      year: 2026,
      month: 3,
      specifications: [
        { salaryType: { id: fastlonnId }, rate: 51800, count: 1, amount: 51800, year: 2026, month: 3, employee: { id: employeeId } },
        { salaryType: { id: bonusId }, rate: 5700, count: 1, amount: 5700, year: 2026, month: 3, employee: { id: employeeId } },
      ],
    }],
  }, { generateTaxDeduction: "true" });

  const txId = tx.data.value?.id;
  const payslipId = tx.data.value?.payslips?.[0]?.id;
  console.log(`\n  Transaction ID: ${txId}`);
  console.log(`  Payslip ID: ${payslipId}`);

  // === VALIDATION PHASE ===
  console.log(`\n=== VALIDATION ===\n`);

  // V1: GET the transaction back
  const txGet = await api("GET", `/salary/transaction/${txId}`, undefined, { fields: "*" });
  console.log("  Transaction:", JSON.stringify(txGet.data.value, null, 2));

  // V2: GET the payslip
  const psGet = await api("GET", `/salary/payslip/${payslipId}`, undefined, { fields: "*" });
  console.log("  Payslip:", JSON.stringify(psGet.data.value, null, 2));

  // V3: List all salary transactions for this employee
  const txList = await api("GET", "/salary/transaction", undefined, { employeeId: String(employeeId), fields: "*" });
  console.log("  All transactions for employee:", JSON.stringify(txList.data, null, 2));

  // V4: GET payslip specifications (the line items)
  const specsUrl = `/salary/specification`;
  const specs = await api("GET", specsUrl, undefined, { payslipId: String(payslipId), fields: "*" });
  console.log("  Payslip specifications:", JSON.stringify(specs.data, null, 2));

  // V5: Check if there's a salary/payment endpoint
  const payments = await api("GET", "/salary/transaction", undefined, { fields: "id,date,year,month,isHistorical", count: "5" });
  console.log("  Recent salary transactions:", JSON.stringify(payments.data.values, null, 2));

  // V6: Check what the evaluator might look for - search by employee
  const empGet = await api("GET", `/employee/${employeeId}`, undefined, { fields: "*" });
  console.log("  Employee after payroll:", JSON.stringify(empGet.data.value?.employments, null, 2));
}

main().catch(console.error);
