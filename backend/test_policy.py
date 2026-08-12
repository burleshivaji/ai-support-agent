"""Checks every demo scenario against the policy engine.

Run:  python test_policy.py   (reloads the demo database first)
"""
from app.demo import load_demo_data
from app.db import get_conn
from app.policy import evaluate_refund

CASES = [
    # order, reason, expected decision, expected rule
    ("ORD-1001", "CHANGE_OF_MIND", "APPROVE", "standard_return"),
    ("ORD-1016", "CANCEL_BEFORE_SHIP", "APPROVE", "pre_shipment_cancellation"),
    ("ORD-1021", "CHANGE_OF_MIND", "DENY", "duplicate_refund"),
    ("ORD-1002", "CHANGE_OF_MIND", "APPROVE", "vip_late_return"),
    ("ORD-1002", "CANCEL_BEFORE_SHIP", "DENY", "reason_not_applicable"),
    ("ORD-1002", "LATE_SHIPMENT", "DENY", "reason_not_applicable"),
    ("ORD-1002", "STOLEN_AFTER_DELIVERY", "DENY", "theft_after_delivery"),
    ("ORD-1003", "CHANGE_OF_MIND", "APPROVE", "high_spend_late_return"),
    ("ORD-1004", "CHANGE_OF_MIND", "DENY", "final_sale"),
    # Final sale still covers a faulty product; the photo is the next step.
    ("ORD-1004", "DAMAGED_OR_DEFECTIVE", "EVIDENCE_REQUIRED", "evidence_required"),
    ("ORD-1005", "CHANGE_OF_MIND", "DENY", "window_expired"),
    ("ORD-1006", "DAMAGED_OR_DEFECTIVE", "EVIDENCE_REQUIRED", "evidence_required"),
    ("ORD-1007", "CHANGE_OF_MIND", "APPROVE", "standard_return"),
    ("ORD-1008", "LATE_SHIPMENT", "ESCALATE", "late_shipment"),
    ("ORD-1009", "NOT_RECEIVED", "APPROVE", "carrier_fault_lost"),
    ("ORD-1010", "NOT_RECEIVED", "APPROVE", "carrier_fault_wrong_address"),
    ("ORD-1011", "STOLEN_AFTER_DELIVERY", "DENY", "theft_after_delivery"),
    ("ORD-1011", "NOT_RECEIVED", "DENY", "delivered_with_proof"),
    ("ORD-1012", "LATE_SHIPMENT", "DENY", "not_yet_delivered"),
    ("ORD-1013", "CHANGE_OF_MIND", "ESCALATE", "high_value"),
    ("ORD-1014", "CHANGE_OF_MIND", "DENY", "suspicious_flags"),
    ("ORD-1017", "NOT_RECEIVED", "APPROVE", "carrier_fault_lost"),
    ("ORD-1015", "CHANGE_OF_MIND", "ESCALATE", "high_value"),
]


def main():
    load_demo_data()
    conn = get_conn()
    fails = 0
    for order_id, reason, exp_dec, exp_rule in CASES:
        order = dict(conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
        order["final_sale"] = bool(order["final_sale"])
        cust = dict(conn.execute("SELECT * FROM customers WHERE id=?",
                                 (order["customer_id"],)).fetchone())
        v = evaluate_refund(conn, order, cust, reason)
        ok = v["decision"] == exp_dec and v["rule"] == exp_rule
        fails += 0 if ok else 1
        mark = "OK  " if ok else "FAIL"
        print(f"{mark} {order_id} {reason:24} -> {v['decision']:8} {v['rule']}")
    # Return lifecycle: creating a return blocks a second request, facility
    # pass issues the refund, and a rejected return ends eligibility.
    from app.tools_core import create_return, resolve_return
    r = create_return("ORD-1001", "ethan.miller@example.com", "CHANGE_OF_MIND", False)
    ok = r.get("created") is True
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1001 create_return (unopened) -> created={r.get('created')}")

    order = dict(conn.execute("SELECT * FROM orders WHERE id='ORD-1001'").fetchone())
    order["final_sale"] = bool(order["final_sale"])
    cust = dict(conn.execute("SELECT * FROM customers WHERE id='CUST-001'").fetchone())
    v = evaluate_refund(conn, order, cust, "CHANGE_OF_MIND")
    ok = v["decision"] == "DENY" and v["rule"] == "return_in_progress"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1001 while return open       -> {v['decision']:8} {v['rule']}")

    rid = int(r["rma"].split("-")[1])
    fr = resolve_return(rid, "pass")
    ok = fr.get("processed") is True and fr.get("total") == 249.0
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} RET pass at facility            -> refund ${fr.get('total')}")

    r2 = create_return("ORD-1007", "liam.parker@example.com", "CHANGE_OF_MIND", False)
    rid2 = int(r2["rma"].split("-")[1])
    resolve_return(rid2, "fail")
    order = dict(conn.execute("SELECT * FROM orders WHERE id='ORD-1007'").fetchone())
    order["final_sale"] = bool(order["final_sale"])
    cust = dict(conn.execute("SELECT * FROM customers WHERE id='CUST-007'").fetchone())
    v = evaluate_refund(conn, order, cust, "CHANGE_OF_MIND")
    ok = v["decision"] == "DENY" and v["rule"] == "return_rejected"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1007 after rejected return  -> {v['decision']:8} {v['rule']}")

    r3 = create_return("ORD-1002", "sophia.carter@example.com", "CHANGE_OF_MIND", True)
    ok = r3.get("created") is False and "photo" in r3.get("message", "").lower()
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1002 opened without photo   -> blocked, asks for photos")

    # Story change: denied on one account, then a competing one. Escalate.
    conn.execute("INSERT INTO claims (order_id, customer_id, reason, decision, created_at) "
                 "VALUES ('ORD-1011', 'CUST-011', 'STOLEN_AFTER_DELIVERY', 'DENY', '2026-01-01')")
    order = dict(conn.execute("SELECT * FROM orders WHERE id='ORD-1011'").fetchone())
    order["final_sale"] = bool(order["final_sale"])
    cust = dict(conn.execute("SELECT * FROM customers WHERE id='CUST-011'").fetchone())
    v = evaluate_refund(conn, order, cust, "DAMAGED_OR_DEFECTIVE")
    ok = v["decision"] == "ESCALATE" and v["rule"] == "story_changed"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1011 story changed          -> {v['decision']:8} {v['rule']}")

    # Same reason repeated is not a story change, just a retry.
    v = evaluate_refund(conn, order, cust, "STOLEN_AFTER_DELIVERY")
    ok = v["rule"] == "theft_after_delivery"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1011 same reason again      -> {v['decision']:8} {v['rule']}")

    # Final sale item reported faulty, with a photo: approved, and it still
    # has to come back and pass inspection.
    conn.execute("INSERT INTO evidence (order_id, customer_id, filename, uploaded_at) "
                 "VALUES ('ORD-1004', 'CUST-004', 'sneaker_fault.jpg', '2026-01-01')")
    order = dict(conn.execute("SELECT * FROM orders WHERE id='ORD-1004'").fetchone())
    order["final_sale"] = bool(order["final_sale"])
    cust = dict(conn.execute("SELECT * FROM customers WHERE id='CUST-004'").fetchone())
    v = evaluate_refund(conn, order, cust, "DAMAGED_OR_DEFECTIVE")
    ok = v["decision"] == "APPROVE" and v["rule"] == "damaged_or_defective"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1004 final sale but faulty  -> {v['decision']:8} {v['rule']}")

    # Damage claim again, now with a photo attached: should approve.
    conn.execute("INSERT INTO evidence (order_id, customer_id, filename, uploaded_at) "
                 "VALUES ('ORD-1006', 'CUST-006', 'damage.jpg', '2026-01-01')")
    order = dict(conn.execute("SELECT * FROM orders WHERE id='ORD-1006'").fetchone())
    order["final_sale"] = bool(order["final_sale"])
    cust = dict(conn.execute("SELECT * FROM customers WHERE id='CUST-006'").fetchone())
    v = evaluate_refund(conn, order, cust, "DAMAGED_OR_DEFECTIVE")
    ok = v["decision"] == "APPROVE" and v["rule"] == "damaged_or_defective"
    fails += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} ORD-1006 with photo attached   -> {v['decision']:8} {v['rule']}")

    conn.close()
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    raise SystemExit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
