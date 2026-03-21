#!/usr/bin/env bun
import { TripletexClient } from '../../src/tripletex';

const BASE = process.env.TRIPLETEX_SANDBOX_URL!;
const TOKEN = process.env.TRIPLETEX_SANDBOX_TOKEN!;
const client = new TripletexClient(BASE, TOKEN);

async function main() {
  console.log("=== Task 19: Employee creation from contract ===\n");

  // Step 1: Departments
  console.log("--- Step 1: Departments ---");
  const depts = await client.get("/department", { fields: "id,name", count: "100" });
  console.log("Departments:", JSON.stringify(depts.values?.map((d: any) => d.name), null, 2));

  // Create test department
  const dept = await client.post("/department", { name: "Innkjøp-test19" });
  const deptId = dept.value?.id;
  console.log("Created dept:", deptId);

  // Step 2: Division
  console.log("\n--- Step 2: Division ---");
  const divs = await client.get("/division", { fields: "id,name", count: "1" });
  let divId = divs.values?.[0]?.id;
  if (!divId) {
    const muni = await client.get("/municipality", { count: "1" });
    const muniId = muni.values?.[0]?.id;
    const div = await client.post("/division", {
      name: "Hovedvirksomhet", organizationNumber: "999999999",
      startDate: "2026-01-01", municipalityDate: "2026-01-01", municipality: { id: muniId }
    });
    divId = div.value?.id;
  }
  console.log("Division ID:", divId);

  // Step 3: Create employee (use valid dummy national ID)
  console.log("\n--- Step 3: Create employee ---");
  const emp = await client.post("/employee", {
    firstName: "Test19", lastName: "Sandbox",
    dateOfBirth: "1990-06-27",
    email: "test19@example.org", bankAccountNumber: "82520201226",
    department: { id: deptId }, userType: "NO_ACCESS"
  });
  const empId = emp.value?.id;
  console.log("Employee ID:", empId);
  console.log("Employee response:", JSON.stringify(emp.value, null, 2));

  // Step 4: Lookup occupationCode
  console.log("\n--- Step 4a: occupationCode by code=3512 ---");
  const occ1 = await client.get("/employee/employment/occupationCode", { code: "3512" });
  console.log("By code=3512:", JSON.stringify(occ1, null, 2));

  console.log("\n--- Step 4b: occupationCode by id=3512 ---");
  const occ1b = await client.get("/employee/employment/occupationCode", { id: "3512" });
  console.log("By id=3512:", JSON.stringify(occ1b, null, 2));

  console.log("\n--- Step 4c: occupationCode wildcard code=3512* ---");
  const occ1c = await client.get("/employee/employment/occupationCode", { code: "3512*", count: "20" });
  console.log("By code=3512*:", JSON.stringify(occ1c.values?.map((o: any) => ({ id: o.id, code: o.code, name: o.nameNO })), null, 2));

  console.log("\n--- Step 4d: First 10 occupationCodes ---");
  const occ2 = await client.get("/employee/employment/occupationCode", { count: "10" });
  console.log("First 10:", JSON.stringify(occ2.values?.map((o: any) => ({ id: o.id, code: o.code, name: o.nameNO })), null, 2));

  // Step 5: Create employment
  console.log("\n--- Step 5: Create employment ---");
  const employment = await client.post("/employee/employment", {
    employee: { id: empId },
    startDate: "2026-08-20",
    division: { id: divId },
    employmentId: "1",
    isMainEmployer: true,
    taxDeductionCode: "loennFraHovedarbeidsgiver",
    employmentDetails: [{
      date: "2026-08-20",
      employmentType: "ORDINARY",
      employmentForm: "PERMANENT",
      remunerationType: "MONTHLY_WAGE",
      workingHoursScheme: "NOT_SHIFT",
      percentageOfFullTimeEquivalent: 100,
      shiftDurationHours: 7.5,
      occupationCode: { id: "3512" },
      annualSalary: 970000
    }]
  });
  console.log("Employment:", JSON.stringify(employment, null, 2));

  // Step 6: Verify
  console.log("\n--- Step 6: Verify employee ---");
  const verify = await client.get(`/employee/${empId}`, { fields: "*" });
  console.log("Final employee:", JSON.stringify(verify.value, null, 2));

  console.log("\n--- API call log ---");
  console.log(client.callLog);
}

main().catch(console.error);
