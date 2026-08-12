import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "support.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    tier TEXT NOT NULL DEFAULT 'STANDARD',      -- STANDARD | VIP
    lifetime_spend REAL NOT NULL DEFAULT 0,
    suspicious_flags INTEGER NOT NULL DEFAULT 0,
    joined TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    item TEXT NOT NULL,
    category TEXT NOT NULL,
    amount_paid REAL NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'CARD', -- CARD | STORE_CREDIT | MIXED
    status TEXT NOT NULL,                        -- PROCESSING | SHIPPED | DELIVERED | REFUNDED | CANCELLED
    order_date TEXT NOT NULL,
    promised_date TEXT,
    delivered_date TEXT,
    shipment_status TEXT NOT NULL DEFAULT 'NOT_SHIPPED', -- NOT_SHIPPED | IN_TRANSIT | DELIVERED | LOST
    delivery_proof TEXT,                         -- MATCH | WRONG_ADDRESS | NULL
    final_sale INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS refunds (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    amount REAL NOT NULL,
    destination TEXT NOT NULL,                   -- CARD | STORE_CREDIT
    reason TEXT,
    rule TEXT,
    confirmation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY,
    order_id TEXT REFERENCES orders(id),
    customer_id TEXT REFERENCES customers(id),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS returns (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    reason TEXT,
    rule TEXT,
    opened INTEGER NOT NULL DEFAULT 0,
    refund_plan TEXT NOT NULL,                   -- JSON: [{destination, amount}]
    status TEXT NOT NULL DEFAULT 'AWAITING_ARRIVAL', -- AWAITING_ARRIVAL | COMPLETED | REJECTED
    ship_by TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    reason TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    order_id TEXT REFERENCES orders(id),
    customer_id TEXT REFERENCES customers(id),
    filename TEXT NOT NULL,
    session_id TEXT,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'chat',        -- chat | voice
    type TEXT NOT NULL,                          -- user_message | assistant_message | tool_call | tool_result | policy_check | decision | retry | error
    content TEXT NOT NULL,                       -- JSON payload
    created_at TEXT NOT NULL
);
"""


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
