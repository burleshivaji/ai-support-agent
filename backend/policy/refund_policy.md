# Refund Policy (refund-policy-v1)

This document is the source of truth for refund decisions. The support agent
must validate every request against these rules using the policy tools. If a
rule fails, the request is denied or escalated. The agent cannot invent
exceptions, and an upset customer is not a reason to bend a rule.

## 1. Refund basis

A full refund means 100% of the amount the customer actually paid, not the
catalog list price. Refunds go back to the original payment source. Store
credit portions are restored as store credit.

## 2. Identity and ownership

The customer must be identified by the email address on their account before
any order is discussed. The agent only acts on orders that belong to the
verified customer. If no matching account or order is found, the agent asks
for more detail, and escalates to a human if it still cannot find one.

## 3. Change-of-mind returns

- Eligible within 14 days of the delivery date.
- Day 15 to 30 after delivery, VIP customers only: refund is split 50% to
  the original payment source and 50% as store credit.
- Day 15 to 21 after delivery, standard customers with lifetime spend above
  $5,000: refund is issued 100% as store credit.
- Outside these windows the request is denied.
- Approval creates a return, not an instant refund. See section 4.

## 4. Returns and facility inspection

Every approved return-type refund follows the same process:

- A return (RMA) is created with a 7 day ship-by deadline.
- If the product has been opened or used, the customer must upload photos
  of the product before the return is created. Sealed, unopened products
  do not need photos.
- The agent must tell the customer up front: the refund is initiated only
  after the product reaches the facility and passes inspection, and if
  inspection finds customer-caused damage or a different item, the refund
  is rejected and no money is returned.
- When the facility receives the item and inspection passes, the refund is
  issued to the planned destinations. If inspection fails, the return is
  rejected and the order is no longer eligible.

## 5. Damaged or defective items

Refundable in full within 7 days of delivery when the customer reports the
item arrived damaged or defective. The customer must first provide a photo
of the damage through the chat upload, and the photo must be attached to
the order before the claim can be evaluated. The refund itself still
follows the return and inspection process in section 4.

## 6. Final sale

Final sale items are not refundable for change of mind or damage caused by
the customer. Verified company or carrier fault overrides final sale.

## 7. Orders that have not been delivered

- Order still processing, shipment not started: cancel the order and issue a
  full refund.
- Shipment in transit and still within the promised delivery window: no
  refund. Explain the expected delivery date.
- Promised delivery date passed and still undelivered: escalate to a human
  so the shipment can be investigated.
- Carrier confirms the shipment is lost: full refund immediately. Carrier
  reimbursement is the company's problem, not the customer's.

## 8. Delivery disputes

- Delivery proof shows the package went to the wrong address: company/carrier
  fault, full refund.
- Delivery proof confirms correct delivery to the registered address and the
  customer reports it stolen afterwards: the request is denied under this
  policy.

## 9. High-value refunds

Any refund above $1,000 must be escalated to a human reviewer. The agent
never approves it directly. Verified company or carrier fault bypasses this
rule.

## 10. Suspicious activity

Customers with 5 or more confirmed suspicious-refund flags are blocked from
automated refunds and the request is denied. Verified company or carrier
fault overrides this block.

## 11. Duplicate protection

An order that has already been refunded is never refunded again. Every
refund is written with an idempotency key so retries cannot move money twice.

## 12. Rule priority

1. Verified facts first: duplicate check, then company/carrier fault.
2. Company/carrier fault overrides final sale, the 14-day window, the
   high-value rule, and the suspicious-flag block.
3. Then account restrictions, final sale, return windows and tier
   exceptions, and the high-value limit, in that order.
4. Escalation is for conflicts, failed verification, and the explicit
   escalation paths above. It is not the default for a clear approve or deny.
