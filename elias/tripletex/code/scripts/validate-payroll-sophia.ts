#!/usr/bin/env bun
const BASE_URL = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const AUTH = "Basic " + btoa(`0:${TOKEN}`);
async function api(m: string, p: string, b?: unknown, q?: Record<string, string>) {
  const u = new URL(`${BASE_URL}${p}`); if (q) for (const [k,v] of Object.entries(q)) u.searchParams.set(k,v);
  const r = await fetch(u.toString(), { method: m, headers: { Authorization: AUTH, "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  const j = await r.json().catch(() => ({})); console.log(`${m} ${p} → ${r.status}`);
  if (r.status >= 400) console.log("  ERR:", JSON.stringify(j).slice(0, 500)); return { s: r.status, d: j };
}
async function main() {
  const uid = Date.now().toString(36);
  console.log(`\n=== PAYROLL VALIDATION (Sophia pattern) uid=${uid} ===\n`);
  const dept = await api("GET", "/department", undefined, { fields: "id", count: "1" });
  const emp = await api("POST", "/employee", { firstName: `TestSophia`, lastName: `V${uid}`, email: `sophia-${uid}@test.no`, dateOfBirth: "1990-01-01", department: { id: dept.d.values[0].id }, userType: "NO_ACCESS" });
  const eid = emp.d.value.id;
  const divs = await api("GET", "/division", undefined, { fields: "id", count: "1" });
  let did = divs.d.values?.[0]?.id;
  if (!did) { const m = await api("GET", "/municipality", undefined, { fields: "id", count: "1" }); const d = await api("POST", "/division", { name: "Div", organizationNumber: "999999999", startDate: "2026-01-01", municipalityDate: "2026-01-01", municipality: { id: m.d.values[0].id } }); did = d.d.value.id; }
  await api("POST", "/employee/employment", { employee: { id: eid }, startDate: "2026-01-01", division: { id: did }, employmentId: "1", isMainEmployer: true, taxDeductionCode: "loennFraHovedarbeidsgiver", employmentDetails: [{ date: "2026-01-01", employmentType: "ORDINARY", employmentForm: "PERMANENT", remunerationType: "MONTHLY_WAGE", workingHoursScheme: "NOT_SHIFT", percentageOfFullTimeEquivalent: 100, shiftDurationHours: 7.5 }] });
  const [s2000, s2002] = await Promise.all([api("GET", "/salary/type", undefined, { number: "2000", fields: "id" }), api("GET", "/salary/type", undefined, { number: "2002", fields: "id" })]);
  const tx = await api("POST", "/salary/transaction", { date: "2026-03-20", year: 2026, month: 3, isHistorical: false, payslips: [{ employee: { id: eid }, date: "2026-03-20", year: 2026, month: 3, specifications: [{ salaryType: { id: s2000.d.values[0].id }, rate: 48350, count: 1, amount: 48350, year: 2026, month: 3, employee: { id: eid } }, { salaryType: { id: s2002.d.values[0].id }, rate: 15450, count: 1, amount: 15450, year: 2026, month: 3, employee: { id: eid } }] }] }, { generateTaxDeduction: "true" });
  const txId = tx.d.value?.id, psId = tx.d.value?.payslips?.[0]?.id;
  console.log(`\nTransaction: ${txId}, Payslip: ${psId}\n\n=== VALIDATION ===\n`);
  const v1 = await api("GET", `/salary/transaction/${txId}`, undefined, { fields: "*" }); console.log("Transaction:", JSON.stringify(v1.d.value, null, 2));
  const v2 = await api("GET", `/salary/payslip/${psId}`, undefined, { fields: "*" }); console.log("Payslip:", JSON.stringify(v2.d.value, null, 2));
  const v3 = await api("GET", "/salary/specification", undefined, { payslipId: String(psId), fields: "*" }); console.log("Specifications:", JSON.stringify(v3.d, null, 2));
}
main().catch(console.error);
