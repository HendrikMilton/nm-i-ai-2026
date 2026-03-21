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
  console.log(`\n=== TRAVEL EXPENSE VALIDATION (Hugo pattern) uid=${uid} ===\n`);
  // Create employee
  const dept = await api("GET", "/department", undefined, { fields: "id", count: "1" });
  const emp = await api("POST", "/employee", { firstName: `TestHugo`, lastName: `V${uid}`, email: `hugo-${uid}@test.no`, dateOfBirth: "1990-01-01", department: { id: dept.d.values[0].id }, userType: "NO_ACCESS" });
  const eid = emp.d.value.id;
  console.log(`Employee: ${eid}`);

  // Create travel expense
  const te = await api("POST", "/travelExpense", { employee: { id: eid }, title: `Conference ${uid}`, date: "2026-03-20" });
  const teId = te.d.value?.id;
  console.log(`Travel expense: ${teId}`);

  // Get cost categories and payment types
  const [cats, ptypes] = await Promise.all([
    api("GET", "/travelExpense/costCategory", undefined, { fields: "id,description", count: "100" }),
    api("GET", "/travelExpense/paymentType", undefined, { fields: "id,description", count: "100" }),
  ]);
  const matId = cats.d.values.find((c: any) => c.description === "Mat")?.id;
  const flyId = cats.d.values.find((c: any) => c.description === "Fly")?.id;
  const taxiId = cats.d.values.find((c: any) => c.description === "Taxi")?.id;
  const payTypeId = ptypes.d.values[0]?.id;
  console.log(`Categories: Mat=${matId}, Fly=${flyId}, Taxi=${taxiId}, PayType=${payTypeId}`);

  // Add costs sequentially - WITH isPaidByEmployee
  const c1 = await api("POST", "/travelExpense/cost", { travelExpense: { id: teId }, costCategory: { id: matId }, paymentType: { id: payTypeId }, date: "2026-03-20", amountCurrencyIncVat: 4000, comments: "Per diem 5 days x 800", isPaidByEmployee: true });
  const c2 = await api("POST", "/travelExpense/cost", { travelExpense: { id: teId }, costCategory: { id: flyId }, paymentType: { id: payTypeId }, date: "2026-03-20", amountCurrencyIncVat: 7700, comments: "Flight", isPaidByEmployee: true });
  const c3 = await api("POST", "/travelExpense/cost", { travelExpense: { id: teId }, costCategory: { id: taxiId }, paymentType: { id: payTypeId }, date: "2026-03-20", amountCurrencyIncVat: 600, comments: "Taxi", isPaidByEmployee: true });

  console.log(`\n=== VALIDATION ===\n`);

  // V1: GET travel expense with all fields
  const teGet = await api("GET", `/travelExpense/${teId}`, undefined, { fields: "*" });
  console.log("Travel expense full:", JSON.stringify(teGet.d.value, null, 2));

  // V2: GET costs
  const costs = await api("GET", "/travelExpense/cost", undefined, { travelExpenseId: String(teId), fields: "*" });
  console.log("Costs:", JSON.stringify(costs.d, null, 2));

  // V3: Check perDiemCompensation endpoint
  const perDiem = await api("GET", "/travelExpense/perDiemCompensation", undefined, { travelExpenseId: String(teId), fields: "*" });
  console.log("PerDiem compensations:", JSON.stringify(perDiem.d, null, 2));

  // V4: Check rate categories
  const rateCats = await api("GET", "/travelExpense/rateCategory", undefined, { fields: "id,description,name,type", count: "50" });
  console.log("Rate categories:", JSON.stringify(rateCats.d.values?.slice(0, 10), null, 2));

  // V5: Check perDiemCompensation create endpoint fields
  console.log("\n--- Trying perDiemCompensation creation ---");
  const pdTest = await api("POST", "/travelExpense/perDiemCompensation", {
    travelExpense: { id: teId },
    rateCategory: { id: rateCats.d.values?.[0]?.id },
    overnightAccommodation: "HOTEL",
    countryCode: "NO",
    location: "Stavanger",
    address: "Stavanger",
    count: 5,
    rate: 800,
    amount: 4000,
    isDeductionForBreakfast: false,
    isLunchDeduction: false,
    isDinnerDeduction: false,
  });
  console.log("PerDiem create result:", JSON.stringify(pdTest.d, null, 2));
}
main().catch(console.error);
