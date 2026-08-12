"""Deterministic refund policy engine (refund-policy-v1).

The LLM never decides a refund on its own. Tools call evaluate_refund(),
which checks the rules in priority order and returns a decision plus the
full list of rule checks so the admin dashboard can show exactly why.
"""
from datetime import datetime, date

HIGH_VALUE_LIMIT = 1000.0
CHANGE_OF_MIND_DAYS = 14
VIP_LATE_DAYS = 30
HIGH_SPEND_LATE_DAYS = 21
HIGH_SPEND_THRESHOLD = 5000.0
DAMAGE_WINDOW_DAYS = 7
FLAG_BLOCK_THRESHOLD = 5

REASONS = [
    "CHANGE_OF_MIND",
    "DAMAGED_OR_DEFECTIVE",
    "NOT_RECEIVED",
    "STOLEN_AFTER_DELIVERY",
    "CANCEL_BEFORE_SHIP",
    "LATE_SHIPMENT",
    "OTHER",
]

# Competing accounts of what happened to the same item. A customer can only
# truthfully claim one of these per order.
EXCLUSIVE_REASONS = (
    "CHANGE_OF_MIND",
    "DAMAGED_OR_DEFECTIVE",
    "NOT_RECEIVED",
    "STOLEN_AFTER_DELIVERY",
)


def _days_since(iso_date: str) -> int:
    d = datetime.fromisoformat(iso_date).date()
    return (date.today() - d).days


def _date_passed(iso_date: str) -> bool:
    return datetime.fromisoformat(iso_date).date() < date.today()


def _original_destination(order) -> str:
    return "STORE_CREDIT" if order["payment_method"] == "STORE_CREDIT" else "CARD"


def evaluate_refund(conn, order, customer, reason: str) -> dict:
    """Returns {decision, rule, explanation, refund: [{destination, amount}], checks}."""
    checks = []
    amount = float(order["amount_paid"])

    def check(rule, passed, detail):
        checks.append({"rule": rule, "result": "pass" if passed else "fail", "detail": detail})
        return passed

    def deny(rule, explanation):
        return {"decision": "DENY", "rule": rule, "explanation": explanation,
                "refund": [], "checks": checks}

    def escalate(rule, explanation):
        return {"decision": "ESCALATE", "rule": rule, "explanation": explanation,
                "refund": [], "checks": checks}

    def approve(rule, explanation, refund, fulfillment="after_return"):
        return {"decision": "APPROVE", "rule": rule, "explanation": explanation,
                "refund": refund, "fulfillment": fulfillment, "checks": checks}

    # Rule 10: duplicate protection comes first.
    prior = conn.execute("SELECT confirmation FROM refunds WHERE order_id = ?",
                         (order["id"],)).fetchone()
    if prior or order["status"] == "REFUNDED":
        check("duplicate_refund", False,
              f"Order {order['id']} already refunded"
              + (f" (confirmation {prior['confirmation']})" if prior else ""))
        return deny("duplicate_refund",
                    "This order has already received a full refund. A second refund is never issued.")
    check("duplicate_refund", True, "No prior refund found for this order")

    ret = conn.execute(
        "SELECT id, status FROM returns WHERE order_id = ? AND status != 'COMPLETED' "
        "ORDER BY id DESC LIMIT 1", (order["id"],)).fetchone()
    if ret and ret["status"] == "AWAITING_ARRIVAL":
        check("no_open_return", False,
              f"Return RET-{ret['id']:04d} already open and awaiting arrival at the facility")
        return deny("return_in_progress",
                    "A return for this order is already in progress. The refund will be "
                    "issued once the item reaches the facility and passes inspection.")
    if ret and ret["status"] == "REJECTED":
        check("no_open_return", False,
              f"Return RET-{ret['id']:04d} was rejected at facility inspection")
        return deny("return_rejected",
                    "The returned item failed facility inspection, so this order is no "
                    "longer eligible for a refund.")
    check("no_open_return", True, "No open or rejected return for this order")

    if order["status"] == "CANCELLED":
        check("order_active", False, "Order was already cancelled")
        return deny("order_cancelled", "This order was already cancelled.")

    # Rule 11 priority 2: verified company/carrier fault overrides everything below.
    if order["shipment_status"] == "LOST":
        check("carrier_fault", True, "Carrier confirmed the outbound shipment LOST")
        return approve("carrier_fault_lost",
                       "Our carrier confirmed this shipment was lost in transit. This is our "
                       "fault, not the customer's. Apologize sincerely and issue the full "
                       "refund immediately.",
                       [{"destination": _original_destination(order), "amount": amount}],
                       fulfillment="immediate")
    if order["delivery_proof"] == "WRONG_ADDRESS":
        check("carrier_fault", True, "Delivery proof shows delivery to the wrong address")
        return approve("carrier_fault_wrong_address",
                       "We checked the delivery record and the package went to the wrong "
                       "address. This is a company/carrier mistake. Apologize sincerely and "
                       "issue the full refund.",
                       [{"destination": _original_destination(order), "amount": amount}],
                       fulfillment="immediate")
    check("carrier_fault", False, "No verified company/carrier fault on this order")

    # These reasons are competing accounts of what happened to the same item,
    # so a customer cannot truthfully claim two of them. Switching to a second
    # one after the first was denied is a story change, and a person decides
    # from here - the agent neither accepts it nor calls the customer a liar.
    if reason in EXCLUSIVE_REASONS:
        prior = conn.execute(
            "SELECT reason FROM claims WHERE order_id = ? AND decision = 'DENY' "
            "AND reason != ? AND reason IN (%s) ORDER BY id DESC LIMIT 1"
            % ",".join("?" * len(EXCLUSIVE_REASONS)),
            (order["id"], reason, *EXCLUSIVE_REASONS)).fetchone()
        if prior:
            check("consistent_claim", False,
                  f"Customer first claimed {prior['reason']} on this order and was denied, "
                  f"now claims {reason}")
            return escalate("story_changed",
                            f"The customer first told us this was a {prior['reason'].lower().replace('_', ' ')} "
                            f"case, that was denied, and they are now describing it as "
                            f"{reason.lower().replace('_', ' ')}. Those cannot both be true, so this "
                            "needs a human to review. Do not accuse the customer, and do not "
                            "process the second claim automatically.")
        check("consistent_claim", True, "No conflicting earlier claim on this order")

    # Rule 6: pre-shipment cancellation.
    if order["status"] == "PROCESSING" and order["shipment_status"] == "NOT_SHIPPED":
        check("pre_shipment", True, "Order still processing, shipment not started")
        return approve("pre_shipment_cancellation",
                       "Shipment has not started, so the order is cancelled with a full refund.",
                       [{"destination": _original_destination(order), "amount": amount}],
                       fulfillment="immediate")

    # Rule 6: in transit.
    if order["status"] == "SHIPPED" or order["shipment_status"] == "IN_TRANSIT":
        if order["promised_date"] and _date_passed(order["promised_date"]):
            check("delivery_window", False,
                  f"Promised delivery {order['promised_date']} has passed, still undelivered")
            return escalate("late_shipment",
                            "The promised delivery date has passed and the order is still in "
                            "transit. Escalating to a human to investigate the shipment.")
        check("delivery_window", True,
              f"Shipment in transit, promised delivery {order['promised_date']}")
        return deny("not_yet_delivered",
                    f"The order is still in transit and within the promised delivery window "
                    f"({order['promised_date']}). It is not eligible for a refund yet.")

    # Rule 9: suspicious activity block.
    flags = int(customer["suspicious_flags"])
    if flags >= FLAG_BLOCK_THRESHOLD:
        check("suspicious_flags", False,
              f"Customer has {flags} confirmed suspicious-refund flags (limit {FLAG_BLOCK_THRESHOLD})")
        return deny("suspicious_flags",
                    "This account has reached the confirmed suspicious-activity limit, so "
                    "automated refunds are blocked. Only verified company or carrier fault overrides this.")
    check("suspicious_flags", True, f"{flags} confirmed flags, below the limit of {FLAG_BLOCK_THRESHOLD}")

    # Must be delivered from here on.
    if order["status"] != "DELIVERED" or not order["delivered_date"]:
        check("delivered", False, f"Order status is {order['status']}, not delivered")
        return deny("not_delivered", "The order has not been delivered, so this request cannot proceed.")
    check("delivered", True, f"Delivered on {order['delivered_date']}")

    # The claimed reason must match the order's actual state. A delivered
    # order cannot be "cancelled before shipping" or claimed as a late
    # shipment; switching reasons after a denial does not create eligibility.
    if reason in ("CANCEL_BEFORE_SHIP", "LATE_SHIPMENT"):
        check("reason_matches_state", False,
              f"Reason {reason} does not apply: order was delivered on {order['delivered_date']}")
        return deny("reason_not_applicable",
                    f"This order was already delivered on {order['delivered_date']}, so "
                    f"'{reason}' does not apply to it. Ask the customer what actually happened "
                    "and, if they simply want to return the item, use CHANGE_OF_MIND.")
    check("reason_matches_state", True, f"Reason {reason} is consistent with a delivered order")

    # Rule 7: delivery disputes. A "not received" or "stolen" claim on a
    # delivered order is checked against the carrier's delivery proof.
    if reason in ("NOT_RECEIVED", "STOLEN_AFTER_DELIVERY"):
        if order["delivery_proof"] == "MATCH":
            check("delivery_proof", False,
                  f"Carrier proof confirms correct delivery to the registered address on "
                  f"{order['delivered_date']}")
            if reason == "STOLEN_AFTER_DELIVERY":
                return deny("theft_after_delivery",
                            "Delivery proof confirms the package was correctly delivered to the "
                            "registered address. Theft after delivery is not covered by the refund policy.")
            return deny("delivered_with_proof",
                        f"Carrier delivery proof shows this order was delivered to the registered "
                        f"address on {order['delivered_date']}. A non-delivery refund cannot be "
                        "issued when correct delivery is confirmed. Share the delivery evidence "
                        "with the customer.")
        check("delivery_proof", True, "No confirmed delivery proof; treating as delivery dispute")
        return escalate("delivery_dispute",
                        "Delivery cannot be confirmed against the registered address. Escalating for review.")

    # Rule 5: final sale. It blocks change-of-mind returns, but not an item
    # that arrived damaged or defective - that is our fault, not the
    # customer's. Facility inspection is what catches customer-caused damage.
    if order["final_sale"] and reason != "DAMAGED_OR_DEFECTIVE":
        check("final_sale", False, "Item is marked final sale")
        return deny("final_sale",
                    "This item was purchased as final sale. It is not refundable for a "
                    "change of mind. It is still covered if it arrived damaged or "
                    "defective, or if there was a company or carrier fault.")
    if order["final_sale"]:
        check("final_sale", True,
              "Item is final sale, but final sale does not block a damaged or defective claim")
    else:
        check("final_sale", True, "Item is not final sale")

    days = _days_since(order["delivered_date"])

    # Rule 4: damaged or defective. Requires photo evidence on file.
    if reason == "DAMAGED_OR_DEFECTIVE":
        ev = conn.execute("SELECT filename FROM evidence WHERE order_id = ?",
                          (order["id"],)).fetchone()
        if not ev:
            checks.append({"rule": "photo_evidence", "result": "fail",
                           "detail": "No damage photo on file for this order"})
            return {"decision": "EVIDENCE_REQUIRED", "rule": "evidence_required",
                    "explanation": "A photo of the damage is required before a damage "
                                   "claim can be evaluated. Ask the customer to upload one.",
                    "refund": [], "checks": checks}
        check("photo_evidence", True, f"Damage photo on file: {ev['filename']}")
        if days <= DAMAGE_WINDOW_DAYS:
            check("damage_window", True, f"Day {days} of {DAMAGE_WINDOW_DAYS}-day damage window")
            refund = [{"destination": _original_destination(order), "amount": amount}]
            if amount > HIGH_VALUE_LIMIT:
                check("high_value", False, f"${amount:.2f} exceeds the ${HIGH_VALUE_LIMIT:.0f} auto-approve limit")
                return escalate("high_value",
                                f"The refund of ${amount:.2f} is above the ${HIGH_VALUE_LIMIT:.0f} limit "
                                "and must be reviewed by a human.")
            check("high_value", True, f"${amount:.2f} is within the ${HIGH_VALUE_LIMIT:.0f} limit")
            return approve("damaged_or_defective",
                           f"Damage reported on day {days}, within the {DAMAGE_WINDOW_DAYS}-day window. Full refund.",
                           refund)
        check("damage_window", False, f"Day {days} is past the {DAMAGE_WINDOW_DAYS}-day damage window")
        return deny("damage_window_expired",
                    f"Damage claims are covered for {DAMAGE_WINDOW_DAYS} days after delivery. "
                    f"This order was delivered {days} days ago.")

    # Rule 3: change-of-mind windows and tier exceptions.
    dest = _original_destination(order)
    if days <= CHANGE_OF_MIND_DAYS:
        check("return_window", True, f"Day {days} of the {CHANGE_OF_MIND_DAYS}-day return window")
        refund = [{"destination": dest, "amount": amount}]
        rule = "standard_return"
        explanation = f"Requested on day {days}, within the {CHANGE_OF_MIND_DAYS}-day window. Full refund."
    elif customer["tier"] == "VIP" and days <= VIP_LATE_DAYS:
        check("return_window", True,
              f"Day {days}: past the {CHANGE_OF_MIND_DAYS}-day window, inside the VIP day-{VIP_LATE_DAYS} exception")
        refund = [{"destination": dest, "amount": round(amount / 2, 2)},
                  {"destination": "STORE_CREDIT", "amount": round(amount / 2, 2)}]
        rule = "vip_late_return"
        explanation = (f"VIP exception on day {days}: 50% back to the original payment source "
                       f"and 50% as store credit.")
    elif float(customer["lifetime_spend"]) > HIGH_SPEND_THRESHOLD and days <= HIGH_SPEND_LATE_DAYS:
        check("return_window", True,
              f"Day {days}: lifetime spend ${customer['lifetime_spend']:.0f} qualifies for the "
              f"day-{HIGH_SPEND_LATE_DAYS} store-credit exception")
        refund = [{"destination": "STORE_CREDIT", "amount": amount}]
        rule = "high_spend_late_return"
        explanation = f"High-spend exception on day {days}: full amount as store credit only."
    else:
        check("return_window", False, f"Day {days} is outside every applicable return window")
        return deny("window_expired",
                    f"The return window has expired. This order was delivered {days} days ago and "
                    f"no late-return exception applies.")

    # Rule 8: high value limit.
    if amount > HIGH_VALUE_LIMIT:
        check("high_value", False, f"${amount:.2f} exceeds the ${HIGH_VALUE_LIMIT:.0f} auto-approve limit")
        return escalate("high_value",
                        f"The refund of ${amount:.2f} is above the ${HIGH_VALUE_LIMIT:.0f} limit and "
                        "must be reviewed by a human.")
    check("high_value", True, f"${amount:.2f} is within the ${HIGH_VALUE_LIMIT:.0f} limit")

    return approve(rule, explanation, refund)
