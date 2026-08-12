"""Demo data for the mock CRM: 15 customers and 18 orders, one per policy
scenario. Dates are relative to today so the return windows line up no
matter when you run the demo.

Run:  python -m app.demo   (rebuilds the database from scratch)
"""
from datetime import date, timedelta, datetime, timezone

from .db import get_conn, init_db, DB_PATH


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def days_ahead(n):
    return (date.today() + timedelta(days=n)).isoformat()


CUSTOMERS = [
    # id, name, tier, email, phone, lifetime_spend, flags
    ("CUST-001", "Ethan Miller", "STANDARD", "ethan.miller@example.com", "555-0101", 820, 0),
    ("CUST-002", "Sophia Carter", "VIP", "sophia.carter@example.com", "555-0102", 8450, 0),
    ("CUST-003", "Daniel Brooks", "STANDARD", "daniel.brooks@example.com", "555-0103", 6280, 0),
    ("CUST-004", "Olivia Turner", "STANDARD", "olivia.turner@example.com", "555-0104", 1240, 0),
    ("CUST-005", "Noah Bennett", "STANDARD", "noah.bennett@example.com", "555-0105", 2760, 0),
    ("CUST-006", "Ava Collins", "VIP", "ava.collins@example.com", "555-0106", 11400, 0),
    ("CUST-007", "Liam Parker", "STANDARD", "liam.parker@example.com", "555-0107", 3120, 0),
    ("CUST-008", "Mia Foster", "STANDARD", "mia.foster@example.com", "555-0108", 4380, 0),
    ("CUST-009", "Lucas Reed", "STANDARD", "lucas.reed@example.com", "555-0109", 980, 0),
    ("CUST-010", "Emma Hayes", "VIP", "emma.hayes@example.com", "555-0110", 9750, 0),
    ("CUST-011", "James Cooper", "STANDARD", "james.cooper@example.com", "555-0111", 1850, 0),
    ("CUST-012", "Amelia Ross", "STANDARD", "amelia.ross@example.com", "555-0112", 2230, 0),
    ("CUST-013", "Benjamin Ward", "STANDARD", "benjamin.ward@example.com", "555-0113", 7900, 1),
    ("CUST-014", "Charlotte Gray", "STANDARD", "charlotte.gray@example.com", "555-0114", 4650, 5),
    ("CUST-015", "Henry Adams", "VIP", "henry.adams@example.com", "555-0115", 13600, 2),
]

# id, customer, item, category, paid, method, status, order_date, promised, delivered,
# shipment_status, delivery_proof, final_sale, scenario the order demonstrates
ORDERS = [
    ("ORD-1001", "CUST-001", "Wireless Headphones", "Electronics", 249.00, "CARD",
     "DELIVERED", days_ago(9), days_ago(6), days_ago(6), "DELIVERED", "MATCH", 0),
    # Standard change of mind, day 6 -> APPROVE full

    ("ORD-1016", "CUST-001", "Bluetooth Speaker", "Electronics", 129.00, "CARD",
     "PROCESSING", days_ago(2), days_ahead(3), None, "NOT_SHIPPED", None, 0),
    # Pre-shipment cancellation -> cancel + full refund

    ("ORD-1021", "CUST-001", "Bluetooth Speaker", "Electronics", 129.00, "CARD",
     "REFUNDED", days_ago(20), days_ago(17), days_ago(17), "DELIVERED", "MATCH", 0),
    # Already refunded -> duplicate DENY

    ("ORD-1002", "CUST-002", "Smart Watch", "Wearables", 300.00, "CARD",
     "DELIVERED", days_ago(22), days_ago(19), days_ago(19), "DELIVERED", "MATCH", 0),
    # VIP, day 19 -> split: $150 card + $150 store credit

    ("ORD-1003", "CUST-003", "Tablet", "Electronics", 649.00, "CARD",
     "DELIVERED", days_ago(21), days_ago(18), days_ago(18), "DELIVERED", "MATCH", 0),
    # Standard, lifetime spend > $5k, day 18 -> 100% store credit

    ("ORD-1004", "CUST-004", "Limited Edition Sneakers", "Footwear", 220.00, "CARD",
     "DELIVERED", days_ago(8), days_ago(5), days_ago(5), "DELIVERED", "MATCH", 1),
    # Final sale -> DENY

    ("ORD-1005", "CUST-005", "Mechanical Keyboard", "Accessories", 119.00, "CARD",
     "DELIVERED", days_ago(43), days_ago(40), days_ago(40), "DELIVERED", "MATCH", 0),
    # Day 40 -> window expired DENY

    ("ORD-1006", "CUST-006", "Smart Watch", "Wearables", 349.00, "CARD",
     "DELIVERED", days_ago(7), days_ago(4), days_ago(4), "DELIVERED", "MATCH", 0),
    # Damaged on arrival, day 4 -> APPROVE full

    ("ORD-1007", "CUST-007", "Smart Watch", "Wearables", 279.00, "CARD",
     "DELIVERED", days_ago(6), days_ago(3), days_ago(3), "DELIVERED", "MATCH", 0),
    # Another standard approval

    ("ORD-1008", "CUST-008", "4K Monitor", "Electronics", 499.00, "CARD",
     "SHIPPED", days_ago(9), days_ago(4), None, "IN_TRANSIT", None, 0),
    # Promised date passed, still in transit -> ESCALATE late shipment

    ("ORD-1009", "CUST-009", "Smartphone", "Electronics", 999.00, "CARD",
     "SHIPPED", days_ago(7), days_ago(2), None, "LOST", None, 0),
    # Carrier confirmed LOST -> full refund (carrier fault)

    ("ORD-1010", "CUST-010", "Tablet", "Electronics", 649.00, "CARD",
     "DELIVERED", days_ago(9), days_ago(6), days_ago(6), "DELIVERED", "WRONG_ADDRESS", 0),
    # Delivered to wrong address -> full refund (carrier fault)

    ("ORD-1011", "CUST-011", "Wireless Headphones", "Electronics", 249.00, "CARD",
     "DELIVERED", days_ago(8), days_ago(5), days_ago(5), "DELIVERED", "MATCH", 0),
    # Correct delivery proof, claims stolen -> DENY

    ("ORD-1012", "CUST-012", "4K Monitor", "Electronics", 499.00, "CARD",
     "SHIPPED", days_ago(3), days_ahead(2), None, "IN_TRANSIT", None, 0),
    # In transit, promised date not passed -> DENY (wait for delivery)

    ("ORD-1013", "CUST-013", "Gaming Laptop", "Computers", 1699.00, "CARD",
     "DELIVERED", days_ago(8), days_ago(5), days_ago(5), "DELIVERED", "MATCH", 0),
    # Over $1,000 -> ESCALATE high value

    ("ORD-1014", "CUST-014", "Mechanical Keyboard", "Accessories", 119.00, "STORE_CREDIT",
     "DELIVERED", days_ago(7), days_ago(4), days_ago(4), "DELIVERED", "MATCH", 0),
    # 5 suspicious flags -> DENY

    ("ORD-1017", "CUST-014", "Smartphone", "Electronics", 999.00, "CARD",
     "SHIPPED", days_ago(6), days_ago(2), None, "LOST", None, 0),
    # Same flagged customer, but carrier LOST -> carrier fault overrides -> refund

    ("ORD-1015", "CUST-015", "Professional Camera", "Electronics", 1899.00, "CARD",
     "DELIVERED", days_ago(11), days_ago(8), days_ago(8), "DELIVERED", "MATCH", 0),
    # VIP but over $1,000 -> ESCALATE high value
]


def load_demo_data():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    conn = get_conn()
    conn.executemany(
        "INSERT INTO customers (id, name, tier, email, phone, lifetime_spend, suspicious_flags, joined) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(*c, days_ago(400)) for c in CUSTOMERS])
    conn.executemany(
        "INSERT INTO orders (id, customer_id, item, category, amount_paid, payment_method, "
        "status, order_date, promised_date, delivered_date, shipment_status, delivery_proof, final_sale) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ORDERS)
    # Historical refund that makes ORD-1021 a duplicate case.
    conn.execute(
        "INSERT INTO refunds (order_id, customer_id, amount, destination, reason, rule, "
        "confirmation, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("ORD-1021", "CUST-001", 129.00, "CARD", "CHANGE_OF_MIND", "standard_return",
         "RF-H1021", "refund:ORD-1021:CARD",
         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    print(f"Demo data loaded: {len(CUSTOMERS)} customers, {len(ORDERS)} orders -> {DB_PATH}")


if __name__ == "__main__":
    load_demo_data()
