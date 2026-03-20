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
  console.log(`\n=== TIMESHEET + PROJECT INVOICE VALIDATION (Miguel pattern) uid=${uid} ===\n`);

  // 1. Create customer
  const cust = await api("POST", "/customer", { name: `TestCust ${uid}`, organizationNumber: "999999999" });
  const custId = cust.d.value?.id;
  console.log(`Customer: ${custId}`);

  // 2. Create employee with STANDARD userType (needed for timesheet)
  const dept = await api("GET", "/department", undefined, { fields: "id", count: "1" });
  const emp = await api("POST", "/employee", { firstName: `TestMiguel`, lastName: `V${uid}`, email: `miguel-${uid}@test.no`, dateOfBirth: "1990-01-01", department: { id: dept.d.values[0].id }, userType: "STANDARD" });
  const eid = emp.d.value?.id;
  console.log(`Employee: ${eid}`);

  // 3. Get who am I for project manager fallback
  const whoami = await api("GET", "/token/session/>whoAmI", undefined, { fields: "employeeId" });
  const adminEmpId = whoami.d.value?.employeeId;
  console.log(`Admin employee: ${adminEmpId}`);

  // 4. Create project
  const proj = await api("POST", "/project", { name: `DataMigration ${uid}`, customer: { id: custId }, projectManager: { id: adminEmpId || eid }, startDate: "2026-01-01", isFixedPrice: false });
  const projId = proj.d.value?.id;
  console.log(`Project: ${projId}`);

  // 5. Get activities for timesheet
  const acts = await api("GET", "/activity/>forTimeSheet", undefined, { projectId: String(projId), fields: "id,name" });
  console.log("Activities for timesheet:", JSON.stringify(acts.d.values?.map((a: any) => `${a.id}:${a.name}`)));
  const analyseAct = acts.d.values?.find((a: any) => a.name?.toLowerCase().includes("analyse"));
  const actId = analyseAct?.id || acts.d.values?.[0]?.id;
  console.log(`Using activity: ${actId} (${analyseAct?.name || acts.d.values?.[0]?.name})`);

  // 6. Create timesheet entry
  const ts = await api("POST", "/timesheet/entry", { employee: { id: eid || adminEmpId }, project: { id: projId }, activity: { id: actId }, date: "2026-03-20", hours: 39 });
  console.log(`Timesheet entry: ${ts.d.value?.id}`);

  // 7. Check if we need hourly rate on project or employee
  console.log(`\n=== Checking project invoicing ===\n`);

  // V1: GET project with all fields
  const projGet = await api("GET", `/project/${projId}`, undefined, { fields: "*" });
  console.log("Project:", JSON.stringify(projGet.d.value, null, 2).slice(0, 1000));

  // V2: Check project hourly rates
  const rates = await api("GET", "/project/hourlyRates", undefined, { projectId: String(projId), fields: "*" });
  console.log("Project hourly rates:", JSON.stringify(rates.d, null, 2));

  // V3: Try to set hourly rate on project
  console.log("\n--- Setting hourly rate ---");
  const rateSet = await api("POST", "/project/hourlyRates", { project: { id: projId }, startDate: "2026-01-01", showInProjectOrder: true, hourlyRatePrices: [{ employee: { id: eid || adminEmpId }, activity: { id: actId }, hourlyRate: 1000 }] });
  console.log("Rate set result:", JSON.stringify(rateSet.d, null, 2).slice(0, 500));

  // V4: Create invoice from project
  console.log("\n--- Creating project invoice ---");
  // First ensure bank account
  const bank = await api("GET", "/ledger/account", undefined, { number: "1920", fields: "id,bankAccountNumber,version" });
  if (!bank.d.values[0]?.bankAccountNumber) {
    await api("PUT", `/ledger/account/${bank.d.values[0].id}`, { id: bank.d.values[0].id, version: bank.d.values[0].version, number: 1920, name: "Bankinnskudd", bankAccountNumber: "12345678903" });
  }

  // Create order linked to project
  const order = await api("POST", "/order", { customer: { id: custId }, orderDate: "2026-03-20", deliveryDate: "2026-03-20", project: { id: projId } });
  const orderId = order.d.value?.id;

  // Add order line for the hours
  const ol = await api("POST", "/order/orderline", { order: { id: orderId }, description: "Analyse - 39 timer", count: 39, unitPriceExcludingVatCurrency: 1000, vatType: { id: 3 } });

  // Create invoice
  const inv = await api("POST", "/invoice", { invoiceDate: "2026-03-20", invoiceDueDate: "2026-04-03", orders: [{ id: orderId }] }, { sendToCustomer: "false" });
  console.log("Invoice:", JSON.stringify(inv.d.value, null, 2).slice(0, 500));

  // V5: GET timesheet entries
  const tsEntries = await api("GET", "/timesheet/entry", undefined, { projectId: String(projId), fields: "*" });
  console.log("\nTimesheet entries:", JSON.stringify(tsEntries.d, null, 2));
}
main().catch(console.error);
