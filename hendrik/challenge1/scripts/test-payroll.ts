#!/usr/bin/env bun
const BASE_URL = "https://kkpqfuj-amager.tripletex.dev/v2";
const SESSION_TOKEN = "REDACTED_TOKEN";
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
  if (res.status >= 400) console.log("  ERROR:", JSON.stringify(json).slice(0, 500));
  return { status: res.status, data: json };
}

async function main() {
  // 1. Find an employee
  const emp = await api("GET", "/employee", undefined, { fields: "id,firstName,lastName,email,userType", count: "5" });
  console.log("Employees:", emp.data.values?.map((e: any) => `${e.id} ${e.firstName} ${e.lastName} (${e.userType})`));
  const employeeId = emp.data.values?.[0]?.id;

  // 2. Check if employee has employment
  const employment = await api("GET", "/employee/employment", undefined, { employeeId: String(employeeId), fields: "id,startDate,endDate,employmentType" });
  console.log("Employments:", JSON.stringify(employment.data.values?.slice(0, 3)));

  // 3. Get salary types
  const salaryTypes = await api("GET", "/salary/type", undefined, { fields: "id,number,name,description", count: "20" });
  console.log("\nSalary types:");
  for (const st of salaryTypes.data.values || []) {
    console.log(`  ${st.id}: ${st.number} - ${st.name}`);
  }

  // 4. Try creating a salary transaction
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth() + 1;

  console.log(`\n=== Creating salary transaction for ${year}-${month} ===`);
  const tx = await api("POST", "/salary/transaction", {
    date: today.toISOString().split("T")[0],
    year,
    month,
    isHistorical: false,
    payslips: [{
      employee: { id: employeeId },
      date: today.toISOString().split("T")[0],
      year,
      month,
      specifications: [{
        salaryType: { id: salaryTypes.data.values?.[0]?.id },
        rate: 49550,
        count: 1,
        amount: 49550,
        year,
        month,
        employee: { id: employeeId },
      }]
    }]
  }, { generateTaxDeduction: "true" });

  if (tx.status < 300) {
    console.log("SUCCESS! Transaction created:", JSON.stringify(tx.data.value, null, 2).slice(0, 500));
  }
}

main().catch(console.error);
