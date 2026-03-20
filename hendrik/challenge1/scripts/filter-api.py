"""
Analyze api-summary.json and filter out obviously irrelevant endpoints.
Prints all tags with endpoint counts, marks which to KEEP vs SKIP.
Run with: python3 scripts/filter-api.py
"""
import json

with open('api-summary.json') as f:
    data = json.load(f)

# Tags that are obviously irrelevant to accounting tasks in the competition
SKIP_TAGS = {
    # Internal/platform/admin stuff
    'accountantDashboard', 'accountantDashboard/news',
    'accountingOffice', 'accountingOffice/client', 'accountingOffice/reconciliations',
    'attestation',
    'platformAgnostic/bank/onboarding',
    'token/consumer', 'token/employee', 'token/session',
    'event', 'event/subscription',
    'addon',
    # Integrations & external services
    'zapier',
    'plugin',
    'altinn', 'altinnInstance',
    'vipps',
    # EHF / invoicing formats
    'document/ehf', 'ehfRecipient',
    # Internal features unlikely in competition
    'dashboard',
    'notification',
    'preferences',
    'appSpecific',
    'callout',
    'segment',
    'internalStatus',
    'signatureCombination',
    # Payroll deep details (unlikely in competition)
    'salary/financeTax', 'salary/financeTax/reconciliation',
    'salary/holidayAllowance', 'salary/holidayAllowance/reconciliation',
    'salary/mandatoryDeduction', 'salary/mandatoryDeduction/reconciliation',
    'salary/payrollTax', 'salary/payrollTax/reconciliation',
    'salary/taxDeduction', 'salary/taxDeduction/reconciliation',
    'salary/compilation', 'salary/compilation/line',
    'salary/setting/holidayAllowance', 'salary/setting/pension',
    'salary/payment', 'salary/payslip',
    # Deep asset management
    'asset',
    # Municipality/region codes
    'municipality',
    # Pickup point logistics
    'pickupPoint',
    # Automation/workflow
    'automation',
    # Result budget deep details
    'resultBudget',
    # PurchaseOrder deep details
    'purchaseOrder/deviation',
    'purchaseOrder/connection',
    'purchaseOrder/orderline',
    'purchaseOrder/purchaseOrderIncomingInvoiceRelation',
    # Timesheet deep details
    'timesheet/allocation', 'timesheet/company', 'timesheet/entry',
    'timesheet/month', 'timesheet/project', 'timesheet/salaryProject',
    'timesheet/settings', 'timesheet/timeClock', 'timesheet/week',
    # Deep inventory
    'inventory/location', 'inventory/inventorycount',
    'inventory/stocktaking', 'inventory/stocktaking/productline',
    # Transport types
    'travelExpense/rate', 'travelExpense/rate/category',
    'travelExpense/rate/categoryGroup',
    # System/company settings
    'company/salesForceAccountInfo', 'company/altinn',
    'company/accounting/office',
    # Remit/payment files
    'remit',
    # Year-end deep internals
    'yearEndAnnualAccounts', 'yearEndDirectTax', 'yearEndNotes',
    'yearEndTaxNote', 'yearEndTaxNoteInternal',
    'yearEnd/corporateTax', 'yearEnd/corporateTax/overview',
    # Bank statement parsing
    'bank/statement',
    # Other deep internals
    'ledger/close', 'ledger/openingBalance',
    'ledger/vatType/rate',
    'supplierInvoice/approvalFlow',
    'supplierInvoice/externalAccounting',
    'supplierInvoice/internalNote',
    'supplierInvoice/paymentStatus',
    'supplierInvoice/voucher',
    'invoice/payment/overdueReminder',
}

print(f"{'TAG':<55} {'COUNT':>5}  {'STATUS'}")
print('=' * 75)

kept = {}
skipped = {}

for tag in sorted(data.keys()):
    endpoints = data[tag]
    count = len(endpoints)
    if tag in SKIP_TAGS:
        status = 'SKIP'
        skipped[tag] = endpoints
    else:
        status = 'KEEP'
        kept[tag] = endpoints
    print(f"{tag:<55} {count:>5}  {status}")

print(f"\n{'=' * 75}")
print(f"KEEP: {len(kept)} tags, {sum(len(v) for v in kept.values())} endpoints")
print(f"SKIP: {len(skipped)} tags, {sum(len(v) for v in skipped.values())} endpoints")

# Write filtered version
with open('api-filtered.json', 'w') as f:
    json.dump(kept, f, indent=2, ensure_ascii=False)

size = len(open('api-filtered.json').read())
print(f"\nWritten api-filtered.json: {size:,} bytes ({size/1024:.0f} KB)")
