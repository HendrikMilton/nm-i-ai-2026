# New Task Type: Currency Payment with Disagio/Agio

## Task Pattern

Prompt mentions: EUR invoice, exchange rate at invoicing vs payment, "disagio" or "valutadifferanse", register payment.

Example prompt:
> Vi sendte en faktura på 4644 EUR til Stormberg AS (org.nr 917157812) da kursen var 11.51 NOK/EUR.
> Kunden har nå betalt, men kursen er 10.84 NOK/EUR.
> Registrer betalingen og bokfør valutadifferansen (disagio) på korrekt konto.

## What Happened (scored unknown — no scoring in log)

- Agent spent 13/25 steps doing confused calculations
- Paid the invoice for full 5805 NOK (the system amount) instead of the actual received NOK
- Disagio voucher first failed 422 (missing customer on 1500 posting), then succeeded on retry
- 2 errors total, massive step waste

## Key Insight

The invoice is stored in the system as NOK (5805 = 4644 × 1.25). The task gives EUR amounts and two exchange rates. The system doesn't know about EUR — the agent must:
1. Calculate the correct NOK amounts from the EUR figures
2. Register payment for the amount actually received in NOK
3. Book the difference as disagio (loss) or agio (gain)

## Correct Math

Given: amount_eur (excl VAT), rate_original, rate_payment

```
invoice_nok_incl_vat = amount_eur * 1.25 * rate_original    (what was invoiced)
payment_nok_incl_vat = amount_eur * 1.25 * rate_payment     (what was received)
disagio = invoice_nok_incl_vat - payment_nok_incl_vat        (positive = loss, negative = gain)
```

For the example:
- Invoice: 4644 × 1.25 × 11.51 = 66,815.55 NOK
- Payment: 4644 × 1.25 × 10.84 = 62,926.20 NOK
- Disagio: 3,889.35 NOK

BUT the invoice in the system is only 5805 NOK (= 4644 × 1.25, as if rate=1). So the system amounts don't match the real EUR amounts. The payment should clear the invoice (paidAmount = system amount = 5805), and the disagio is booked as a separate voucher.

Actually, rethinking: the payment registers that the invoice is paid. The disagio voucher adjusts the books for the currency loss. The paidAmount should equal the invoice amount (5805) to clear it — the currency difference is handled by the voucher.

The disagio calculation based on the actual EUR amounts:
- disagio = amount_eur * (rate_original - rate_payment) = 4644 * (11.51 - 10.84) = 4644 * 0.67 = **3,111.48 NOK**

This is excl VAT. Whether VAT applies to the disagio depends on interpretation — currency differences are typically VAT-exempt (vatType 0).

## Proposed Workflow

```
## Workflow: Currency payment with disagio/agio
Register payment on a foreign currency invoice and book the exchange rate difference.
1. In parallel: GET /customer?organizationNumber=X, GET /invoice/paymentType?fields=id,description,
   GET /ledger/account?number=8160&fields=id (Valutatap/disagio) OR 8060 (Valutagevinst/agio),
   GET /ledger/account?number=1500&fields=id (Kundefordringer)
2. GET /invoice?customerId=X&invoiceDateFrom=2020-01-01&invoiceDateTo=2026-12-31&fields=id,amount,amountOutstanding
3. Calculate disagio in ONE call:
   calculate({expression: "<amount_eur> * (<rate_original> - <rate_payment>)"})
   If rate_original > rate_payment → disagio (loss), use account 8160.
   If rate_original < rate_payment → agio (gain), use account 8060.
4. PUT /invoice/{id}/:payment with paymentDate=<today>, paymentTypeId=<"Betalt til bank" id>,
   paidAmount=<invoice amount from system> — clears the invoice at its system amount.
5. POST /ledger/voucher for the currency difference:
   {date:<today>, description:"Disagio faktura <nr> <customer_name>", postings: [
     {date:<today>, description:"Valutatap", account:{id:<8160>},
      amountGross:<disagio>, amountGrossCurrency:<disagio>, vatType:{id:0}, row:1},
     {date:<today>, description:"Valutatap", account:{id:<1500>}, customer:{id:<customer_id>},
      amountGross:-<disagio>, amountGrossCurrency:-<disagio>, vatType:{id:0}, row:2}
   ]}
   CRITICAL: The 1500 (Kundefordringer) posting MUST include customer:{id} — omitting it causes 422.
   For agio (gain): flip signs (debit 1500, credit 8060).
Total: 2 write calls. Zero errors.
```

## Gotchas

- Account 1500 postings REQUIRE `customer:{id}` — always include it
- Disagio is VAT-exempt — always use vatType:{id:0}
- The system invoice amount ≠ real EUR×rate amount. Pay the system amount to clear the invoice.
- Do NOT waste steps recalculating — one calculate call: `amount_eur * (rate_old - rate_new)`
- If the task says "agio" (gain) instead of "disagio" (loss), use account 8060 and flip the signs

## Open Questions

- Is the disagio calculated on the amount excl VAT (4644 * 0.67 = 3111.48) or incl VAT (5805 * 0.67 = 3889.35)?
  The excl VAT interpretation (3111.48) is more standard for Norwegian accounting since VAT is settled separately.
  Need to test both and check which passes.
- Does the checker expect the payment to be the actual NOK received (50340.96) rather than the system amount (5805)?
  This seems unlikely since the invoice system amount is 5805 and paidAmount > invoice amount would be odd.
