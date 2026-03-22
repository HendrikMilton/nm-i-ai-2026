# Task 22 — Receipt/Expense: travelExpense Fix

## Status

0 points across 15+ attempts. Three approaches tried (manual voucher, supplier invoice, travelExpense+convert), all score 0/5. The current system prompt has travelExpense WITHOUT convert but it has **never been tested in competition**.

## Why previous approaches failed

| Approach | Why 0/5 |
|----------|---------|
| Manual voucher (POST /ledger/voucher) | Checker expects travelExpense entity, not ledger postings |
| Supplier invoice (POST /supplierInvoice) | Same — correct ledger postings but no travelExpense entity |
| travelExpense WITH /:convert | Clears title to "", corrupts entity type |

## What has never been tested

travelExpense WITHOUT /:convert, WITH /:deliver + /:approve. This is in the current system prompt but the agent keeps going rogue and using other approaches.

## Agent going rogue

Even when the system prompt says travelExpense, the agent uses manual vouchers or supplier invoices in actual runs. Need stronger instructions.

## Proposed system prompt replacement

```
## Workflow: Receipt/expense registration (Task 22)
Triggered by: "kvittering" / "receipt" / "recibo" / "Quittung" + item name + department name.
MANDATORY: Use the travelExpense API. NEVER use POST /ledger/voucher. NEVER use POST /supplierInvoice.
These alternatives have been tested 15+ times and ALWAYS score 0. Only travelExpense works.
DO NOT use PUT /travelExpense/:convert — it clears the title and corrupts the type.
1. In parallel: GET /employee?fields=id,firstName,lastName&count=1,
   GET /department?name=<dept>&fields=id,name,
   GET /travelExpense/costCategory?fields=id,description,account(id,number),vatType(id)&count=100,
   GET /travelExpense/paymentType?fields=id,description
2. POST /travelExpense with {employee:{id}, title:"<item> - <store_name>", date:<receipt_date>,
   department:{id}, travelDetails:{isForeignTravel:false, isDayTrip:true, isCompensationFromRates:false,
   departureDate:"<receipt_date>", returnDate:"<receipt_date>", departureFrom:"Oslo", destination:"Oslo",
   departureTime:"08:00", returnTime:"09:00", purpose:"<item> - <store_name>"}}
3. POST /travelExpense/cost with {travelExpense:{id}, costCategory:{id:<matching_category>},
   paymentType:{id:<first_available>}, date:<receipt_date>,
   amountCurrencyIncVat:<item_amount_incl_vat>, comments:"<item_description>"}
   Cost category mapping: Togbillett→"Tog", USB/Tastatur/Data→"Data/EDB-kostnad" or "Kontorrekvisita",
   Oppbevaringsboks/Skrivebordlampe→"Kontorrekvisita", Overnatting/Hotell→"Hotell",
   Kaffemøte→"Møte, kurs, oppdatering o.l.", Middag→"Representasjon - fradragsb.",
   Taxi→"Taxi", Fly/Flybillett→"Fly", Buss→"Buss".
   Pick the BEST match from the costCategory list returned in step 1.
4. PUT /travelExpense/:deliver?id={id} (empty body)
5. PUT /travelExpense/:approve?id={id} (empty body)
   Final state must be APPROVED (OPEN→DELIVERED→APPROVED).
   Total: 4 write calls.
```

## Key changes from current prompt

1. **Stronger "NEVER" language** — explicitly bans /ledger/voucher and /supplierInvoice with evidence (15+ failures)
2. **Added trigger keywords** — helps the agent identify this task type in multiple languages
3. **Added travelDetails** — the POST /travelExpense may require travelDetails to fully initialize the entity (the travel expense workflow for other tasks includes it)
4. **Added date field** — ensures the receipt date is on the travelExpense itself
5. **Expanded cost category mapping** — more item→category matches to reduce guessing
6. **Corrected write call count** — 4 calls: travelExpense + cost + deliver + approve
