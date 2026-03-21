#!/usr/bin/env bun
/**
 * Validate supplier creation — create supplier, then GET it back and compare field by field.
 */
const BASE_URL = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const AUTH = "Basic " + btoa(`0:${TOKEN}`);

async function api(m: string, p: string, b?: unknown, q?: Record<string, string>) {
  const u = new URL(`${BASE_URL}${p}`);
  if (q) for (const [k, v] of Object.entries(q)) u.searchParams.set(k, v);
  const r = await fetch(u.toString(), { method: m, headers: { Authorization: AUTH, "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status >= 400) console.log(`  ${m} ${p} → ${r.status} ERR:`, JSON.stringify(j).slice(0, 300));
  return { s: r.status, d: j };
}

async function main() {
  const uid = Date.now().toString(36);
  const supplierName = `TestSupplier ${uid}`;
  const orgNum = "889586605";
  const email = `faktura@test-${uid}.no`;

  console.log(`\n=== SUPPLIER FIELD-BY-FIELD VALIDATION ===\n`);

  // CREATE — exactly as the agent does
  const created = await api("POST", "/supplier", {
    name: supplierName,
    organizationNumber: orgNum,
    email: email,
    invoiceEmail: email,
    showProducts: true,
  });

  if (created.s >= 400) { console.log("CREATE FAILED:", JSON.stringify(created.d)); return; }

  const id = created.d.value.id;
  console.log(`Created supplier ID: ${id}\n`);

  // GET — fetch it back with all fields
  const fetched = await api("GET", `/supplier/${id}`, undefined, { fields: "*" });
  const v = fetched.d.value;

  // Expected values
  const expected: Record<string, any> = {
    name: supplierName,
    organizationNumber: orgNum,
    email: email,
    invoiceEmail: email,
    isSupplier: true,
    isCustomer: false,
    isInactive: false,
    showProducts: true,
    phoneNumber: "",
    phoneNumberMobile: "",
    description: "",
    isPrivateIndividual: false,
    overdueNoticeEmail: "",
    language: "NO",
    website: "",
  };

  console.log("FIELD-BY-FIELD COMPARISON:\n");
  console.log(`${"Field".padEnd(30)} ${"Expected".padEnd(30)} ${"Actual".padEnd(30)} Result`);
  console.log("-".repeat(100));

  let passCount = 0;
  let failCount = 0;

  for (const [field, exp] of Object.entries(expected)) {
    const actual = v[field];
    const match = JSON.stringify(actual) === JSON.stringify(exp);
    const status = match ? "PASS" : "FAIL";
    if (match) passCount++; else failCount++;
    console.log(`${field.padEnd(30)} ${String(exp).padEnd(30)} ${String(actual).padEnd(30)} ${status}`);
  }

  // Also show ALL fields from the response that we didn't check
  console.log("\n\nALL FIELDS IN RESPONSE (unchecked ones marked with *):\n");
  for (const [field, actual] of Object.entries(v)) {
    const checked = field in expected;
    const val = typeof actual === "object" ? JSON.stringify(actual) : String(actual);
    console.log(`${checked ? " " : "*"} ${field.padEnd(30)} ${val.slice(0, 60)}`);
  }

  console.log(`\n\nSUMMARY: ${passCount} passed, ${failCount} failed out of ${passCount + failCount} checked fields`);

  // Now also check: does a GET /customer with this org number find anything?
  console.log("\n\n=== CROSS-CHECK: Is supplier also a customer? ===");
  const custCheck = await api("GET", "/customer", undefined, { organizationNumber: orgNum, fields: "id,name,isCustomer,isSupplier" });
  console.log("Customer search result:", JSON.stringify(custCheck.d, null, 2));

  // Also check GET /supplier search
  console.log("\n=== CROSS-CHECK: GET /supplier search ===");
  const suppCheck = await api("GET", "/supplier", undefined, { organizationNumber: orgNum, fields: "id,name,isCustomer,isSupplier,email,invoiceEmail" });
  console.log("Supplier search result:", JSON.stringify(suppCheck.d, null, 2));
}

main().catch(console.error);
