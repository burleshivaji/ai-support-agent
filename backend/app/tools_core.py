"""Core tool implementations shared by the LangGraph chat agent and the
voice pipeline. Every call and result is logged to the admin dashboard.
The policy engine makes the actual decision; process_refund re-validates
before touching money, so the LLM cannot approve anything by itself.
"""
import difflib
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .db import get_conn
from .logbus import current_session, log_event
from .policy import evaluate_refund, REASONS

POLICY_PATH = Path(__file__).resolve().parent.parent / "policy" / "refund_policy.md"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _order_dict(row):
    d = dict(row)
    d["final_sale"] = bool(d["final_sale"])
    return d


def _present_order(row) -> dict:
    """Order as shown to the agent/customer: empty fields get a readable
    label. The policy engine keeps using the raw values."""
    d = _order_dict(row)
    if not d["delivered_date"]:
        d["delivered_date"] = {"NOT_SHIPPED": "not shipped yet",
                               "IN_TRANSIT": "in transit",
                               "LOST": "never arrived (carrier lost it)"}.get(
            d["shipment_status"], "not delivered yet")
    if not d["delivery_proof"]:
        d["delivery_proof"] = {"NOT_SHIPPED": "pending shipment",
                               "IN_TRANSIT": "pending delivery",
                               "LOST": "none (shipment lost)"}.get(
            d["shipment_status"], "none yet")
    return d


def _log_call(name, args):
    log_event("tool_call", {"tool": name, "args": args})


def _log_result(name, result):
    log_event("tool_result", {"tool": name, "result": result})


def _verified_customer(conn, contact):
    """Match a customer by the email or phone number on the account.
    Phone numbers are compared digits-only, so 5550102, 555-0102 and
    +1 555 0102 all match the same account."""
    c = contact.strip()
    row = conn.execute(
        "SELECT * FROM customers WHERE lower(email) = lower(?) OR phone = ?",
        (c, c)).fetchone()
    if row:
        return row
    digits = re.sub(r"\D", "", c)
    if len(digits) >= 7:
        for r in conn.execute("SELECT * FROM customers WHERE phone IS NOT NULL"):
            stored = re.sub(r"\D", "", r["phone"])
            if digits == stored or digits.endswith(stored) or stored.endswith(digits):
                return r
    return None


def _owned_order(conn, order_id, customer):
    return conn.execute("SELECT * FROM orders WHERE id = ? AND customer_id = ?",
                        (order_id.strip().upper(), customer["id"])).fetchone()


def lookup_customer(email_or_phone: str) -> dict:
    """Find a customer by email or phone and return their profile with all orders."""
    _log_call("lookup_customer", {"email_or_phone": email_or_phone})
    conn = get_conn()
    cust = _verified_customer(conn, email_or_phone)
    if not cust:
        emails = [r["email"] for r in conn.execute("SELECT email FROM customers")]
        conn.close()
        near_miss = bool(difflib.get_close_matches(
            email_or_phone.strip().lower(), emails, n=1, cutoff=0.85))
        if near_miss:
            result = {"found": False,
                      "message": "No exact account match, but the email is very close to one "
                                 "on file, so it may be misspelled or misheard. Politely ask "
                                 "the customer to spell the email again carefully. Never guess "
                                 "or reveal any account email yourself."}
        else:
            result = {"found": False,
                      "message": "No account matches that email or phone number. "
                                 "Ask the customer to re-check it."}
        _log_result("lookup_customer", result)
        return result
    orders = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC",
        (cust["id"],)).fetchall()
    conn.close()
    order_summaries = []
    for o in orders:
        p = _present_order(o)
        order_summaries.append({k: p[k] for k in
                                ("id", "item", "category", "amount_paid", "status",
                                 "order_date", "delivered_date")})
    result = {
        "found": True,
        "customer": {"id": cust["id"], "name": cust["name"], "email": cust["email"],
                     "tier": cust["tier"], "lifetime_spend": cust["lifetime_spend"],
                     "suspicious_flags": cust["suspicious_flags"]},
        "orders": order_summaries,
    }
    _log_result("lookup_customer", {"found": True, "customer": cust["name"],
                                    "orders": len(result["orders"])})
    return result


def get_order(order_id: str, customer_email: str) -> dict:
    """Full detail for one order, only if it belongs to the verified customer."""
    _log_call("get_order", {"order_id": order_id, "customer_email": customer_email})
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("get_order", result)
        return result
    order = _owned_order(conn, order_id, cust)
    conn.close()
    if not order:
        result = {"error": f"Order {order_id} does not belong to this customer or does not exist."}
        _log_result("get_order", result)
        return result
    result = {"order": _present_order(order)}
    _log_result("get_order", {"order": order["id"], "status": order["status"],
                              "amount_paid": order["amount_paid"]})
    return result


def get_refund_policy() -> dict:
    """Return the full refund policy text."""
    _log_call("get_refund_policy", {})
    text = POLICY_PATH.read_text()
    _log_result("get_refund_policy", {"length": len(text)})
    return {"policy": text}


def check_refund_eligibility(order_id: str, customer_email: str, reason: str) -> dict:
    """Run the deterministic policy engine and report every rule check."""
    _log_call("check_refund_eligibility",
              {"order_id": order_id, "customer_email": customer_email, "reason": reason})
    if reason not in REASONS:
        result = {"error": f"reason must be one of {REASONS}"}
        _log_result("check_refund_eligibility", result)
        return result
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("check_refund_eligibility", result)
        return result
    order = _owned_order(conn, order_id, cust)
    if not order:
        conn.close()
        result = {"error": f"Order {order_id} does not belong to this customer or does not exist."}
        _log_result("check_refund_eligibility", result)
        return result

    verdict = evaluate_refund(conn, _order_dict(order), dict(cust), reason)
    conn.close()

    for c in verdict["checks"]:
        log_event("policy_check", {"order_id": order["id"], **c})
    log_event("decision", {"stage": "eligibility", "order_id": order["id"],
                           "decision": verdict["decision"], "rule": verdict["rule"],
                           "refund": verdict["refund"]})
    if verdict["decision"] == "APPROVE":
        if verdict.get("fulfillment") == "immediate":
            next_action = "Confirm with the customer, then call process_refund."
        elif reason == "DAMAGED_OR_DEFECTIVE":
            next_action = ("Call create_return with opened=true now. Photos are already "
                           "on file - do not ask whether the product was opened.")
        else:
            next_action = ("Ask whether the product has been opened or used, then call "
                           "create_return. Opened products need a photo: if the customer "
                           "already uploaded one in this chat, call attach_evidence (no "
                           "filename needed) instead of asking again; otherwise ask them "
                           "to upload one.")
    elif verdict["decision"] == "EVIDENCE_REQUIRED":
        next_action = ("Ask the customer to upload a photo of the damage, call "
                       "attach_evidence with the file name, then re-run this check.")
    elif verdict["decision"] == "ESCALATE":
        next_action = "Call escalate_to_human and tell the customer a person will review it."
    else:
        next_action = "Explain the denial politely, citing the rule. Do not retry other reasons."

    result = {"decision": verdict["decision"], "rule": verdict["rule"],
              "explanation": verdict["explanation"], "refund": verdict["refund"],
              "fulfillment": verdict.get("fulfillment"), "next_action": next_action}
    _log_result("check_refund_eligibility", result)
    return result


def _execute_refund(conn, order, cust, parts, reason, rule) -> dict:
    """Write the refund rows and update the order, with idempotency guards.
    Shared by process_refund (immediate cases) and facility resolution."""
    confirmation = "RF-" + secrets.token_hex(4).upper()
    try:
        for part in parts:
            key = f"refund:{order['id']}:{part['destination']}"
            conn.execute(
                "INSERT INTO refunds (order_id, customer_id, amount, destination, reason, "
                "rule, confirmation, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (order["id"], cust["id"], part["amount"], part["destination"], reason,
                 rule, confirmation, key, _now()))
        new_status = "CANCELLED" if rule == "pre_shipment_cancellation" else "REFUNDED"
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order["id"]))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        existing = conn.execute("SELECT confirmation FROM refunds WHERE order_id = ?",
                                (order["id"],)).fetchone()
        existing = existing["confirmation"] if existing else None
        log_event("error", {"tool": "execute_refund", "order_id": order["id"],
                            "error": str(exc), "existing_confirmation": existing})
        return {"processed": False,
                "message": "Refund already processed" if existing else f"Refund write failed: {exc}",
                "confirmation": existing}
    total = sum(p["amount"] for p in parts)
    log_event("decision", {"stage": "refund_processed", "order_id": order["id"],
                           "rule": rule, "confirmation": confirmation,
                           "total": total, "parts": parts})
    return {"processed": True, "confirmation": confirmation, "total": total,
            "parts": parts, "rule": rule, "order_status": new_status}


def process_refund(order_id: str, customer_email: str, reason: str) -> dict:
    """Execute an immediately-payable refund (carrier fault or pre-shipment
    cancellation). Re-validates policy server-side first. Refunds that need
    a physical return are rejected here and must go through create_return."""
    _log_call("process_refund",
              {"order_id": order_id, "customer_email": customer_email, "reason": reason})
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("process_refund", result)
        return result
    order = _owned_order(conn, order_id, cust)
    if not order:
        conn.close()
        result = {"error": f"Order {order_id} does not belong to this customer or does not exist."}
        _log_result("process_refund", result)
        return result

    verdict = evaluate_refund(conn, _order_dict(order), dict(cust), reason)
    if verdict["decision"] != "APPROVE":
        conn.close()
        log_event("decision", {"stage": "process_refund_blocked", "order_id": order["id"],
                               "decision": verdict["decision"], "rule": verdict["rule"]})
        result = {"processed": False, "decision": verdict["decision"], "rule": verdict["rule"],
                  "explanation": verdict["explanation"],
                  "message": "Refund blocked by the policy engine. Do not promise this refund."}
        _log_result("process_refund", result)
        return result
    if verdict.get("fulfillment") != "immediate":
        conn.close()
        result = {"processed": False,
                  "message": "This refund requires the item to be shipped back first. "
                             "Use create_return; the refund is issued after the facility "
                             "receives and inspects the item."}
        _log_result("process_refund", result)
        return result

    result = _execute_refund(conn, order, cust, verdict["refund"], reason, verdict["rule"])
    conn.close()
    result["explanation"] = verdict["explanation"]
    _log_result("process_refund", result)
    return result


def create_return(order_id: str, customer_email: str, reason: str, opened: bool) -> dict:
    """Create a return (RMA) for an approved return-type refund. The refund
    itself is issued only after the facility receives and inspects the item.
    Opened products require an uploaded photo before the return is created."""
    _log_call("create_return", {"order_id": order_id, "customer_email": customer_email,
                                "reason": reason, "opened": opened})
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("create_return", result)
        return result
    order = _owned_order(conn, order_id, cust)
    if not order:
        conn.close()
        result = {"error": f"Order {order_id} does not belong to this customer or does not exist."}
        _log_result("create_return", result)
        return result

    verdict = evaluate_refund(conn, _order_dict(order), dict(cust), reason)
    if verdict["decision"] != "APPROVE":
        conn.close()
        log_event("decision", {"stage": "create_return_blocked", "order_id": order["id"],
                               "decision": verdict["decision"], "rule": verdict["rule"]})
        result = {"created": False, "decision": verdict["decision"], "rule": verdict["rule"],
                  "explanation": verdict["explanation"]}
        _log_result("create_return", result)
        return result
    if verdict.get("fulfillment") == "immediate":
        conn.close()
        result = {"created": False,
                  "message": "No physical return is needed for this case. Use process_refund."}
        _log_result("create_return", result)
        return result
    if opened:
        ev = conn.execute("SELECT filename FROM evidence WHERE order_id = ?",
                          (order["id"],)).fetchone()
        if not ev:
            conn.close()
            result = {"created": False,
                      "message": "The product is opened, so photos are required before the "
                                 "return can be created. Ask the customer to upload photos "
                                 "of the product in the chat, then attach them with "
                                 "attach_evidence and call create_return again."}
            _log_result("create_return", result)
            return result

    ship_by = (date.today() + timedelta(days=7)).isoformat()
    cur = conn.execute(
        "INSERT INTO returns (order_id, customer_id, reason, rule, opened, refund_plan, "
        "ship_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (order["id"], cust["id"], reason, verdict["rule"], int(opened),
         json.dumps(verdict["refund"]), ship_by, _now()))
    conn.commit()
    rma = f"RET-{cur.lastrowid:04d}"
    conn.close()
    total = sum(p["amount"] for p in verdict["refund"])
    log_event("decision", {"stage": "return_created", "order_id": order["id"],
                           "rma": rma, "rule": verdict["rule"], "opened": bool(opened),
                           "ship_by": ship_by, "planned_refund": verdict["refund"]})
    result = {"created": True, "rma": rma, "ship_by": ship_by,
              "planned_refund": verdict["refund"], "planned_total": total,
              "rule": verdict["rule"],
              "instructions": f"Ship the item back by {ship_by}. The refund of "
                              f"${total:.2f} will be issued after the item reaches our "
                              "facility and passes inspection. If inspection finds "
                              "customer-caused damage or a different item, the refund "
                              "will be rejected."}
    _log_result("create_return", result)
    return result


def resolve_return(return_id: int, outcome: str) -> dict:
    """Facility action, called from the admin dashboard: the item arrived and
    inspection either passed (refund issued) or failed (refund rejected)."""
    conn = get_conn()
    ret = conn.execute("SELECT * FROM returns WHERE id = ?", (return_id,)).fetchone()
    if not ret or ret["status"] != "AWAITING_ARRIVAL":
        conn.close()
        return {"error": "Return not found or already resolved."}
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (ret["order_id"],)).fetchone()
    cust = conn.execute("SELECT * FROM customers WHERE id = ?", (ret["customer_id"],)).fetchone()
    rma = f"RET-{ret['id']:04d}"

    if outcome == "pass":
        result = _execute_refund(conn, order, cust, json.loads(ret["refund_plan"]),
                                 ret["reason"], ret["rule"])
        if result.get("processed"):
            conn.execute("UPDATE returns SET status = 'COMPLETED', resolved_at = ? WHERE id = ?",
                         (_now(), ret["id"]))
            conn.commit()
        conn.close()
        result["rma"] = rma
        return result

    conn.execute("UPDATE returns SET status = 'REJECTED', resolved_at = ? WHERE id = ?",
                 (_now(), ret["id"]))
    conn.commit()
    conn.close()
    log_event("decision", {"stage": "return_rejected", "order_id": ret["order_id"],
                           "rma": rma,
                           "detail": "Facility inspection failed: customer-caused damage "
                                     "or item mismatch. No refund issued."})
    return {"processed": False, "rma": rma, "status": "REJECTED"}


def attach_evidence(order_id: str, customer_email: str, filename: str = "") -> dict:
    """Link an uploaded photo to the customer's order. When no filename is
    given, the customer's most recent unattached upload in this session is
    used automatically."""
    _log_call("attach_evidence",
              {"order_id": order_id, "customer_email": customer_email, "filename": filename})
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("attach_evidence", result)
        return result
    order = _owned_order(conn, order_id, cust)
    if not order:
        conn.close()
        result = {"error": f"Order {order_id} does not belong to this customer or does not exist."}
        _log_result("attach_evidence", result)
        return result

    attached = []
    if filename.strip():
        safe_name = Path(filename.strip()).name
        row = conn.execute(
            "SELECT id, filename FROM evidence WHERE filename = ? AND order_id IS NULL "
            "ORDER BY id DESC LIMIT 1", (safe_name,)).fetchone()
        if row:
            conn.execute("UPDATE evidence SET order_id = ?, customer_id = ? WHERE id = ?",
                         (order["id"], cust["id"], row["id"]))
            attached.append(row["filename"])
        elif (UPLOAD_DIR / safe_name).exists():
            conn.execute(
                "INSERT INTO evidence (order_id, customer_id, filename, session_id, uploaded_at) "
                "VALUES (?,?,?,?,?)",
                (order["id"], cust["id"], safe_name, current_session.get(), _now()))
            attached.append(safe_name)
        else:
            conn.close()
            result = {"error": f"No uploaded file named {safe_name} was found. "
                               "Ask the customer to upload the photo first."}
            _log_result("attach_evidence", result)
            return result
    else:
        # Attach every photo the customer uploaded in this session that is
        # not yet linked to an order.
        rows = conn.execute(
            "SELECT id, filename FROM evidence WHERE session_id = ? AND order_id IS NULL "
            "ORDER BY id", (current_session.get(),)).fetchall()
        if not rows:
            conn.close()
            result = {"error": "No uploaded photo found in this conversation. "
                               "Ask the customer to upload one using the chat upload button."}
            _log_result("attach_evidence", result)
            return result
        for row in rows:
            conn.execute("UPDATE evidence SET order_id = ?, customer_id = ? WHERE id = ?",
                         (order["id"], cust["id"], row["id"]))
            attached.append(row["filename"])
    conn.commit()
    conn.close()
    result = {"attached": True, "order_id": order["id"], "count": len(attached),
              "filenames": attached,
              "message": f"{len(attached)} photo(s) attached to the order. "
                         "Re-run check_refund_eligibility now."}
    _log_result("attach_evidence", result)
    return result


def escalate_to_human(order_id: str, customer_email: str, reason: str) -> dict:
    """Open a ticket for a human reviewer."""
    _log_call("escalate_to_human",
              {"order_id": order_id, "customer_email": customer_email, "reason": reason})
    conn = get_conn()
    cust = _verified_customer(conn, customer_email)
    if not cust:
        conn.close()
        result = {"error": "Customer not verified. Look up the customer by email first."}
        _log_result("escalate_to_human", result)
        return result
    order = _owned_order(conn, order_id, cust)
    order_id_val = order["id"] if order else None
    cur = conn.execute(
        "INSERT INTO escalations (order_id, customer_id, reason, created_at) VALUES (?,?,?,?)",
        (order_id_val, cust["id"], reason, _now()))
    conn.commit()
    ticket = f"ESC-{cur.lastrowid:04d}"
    conn.close()
    log_event("decision", {"stage": "escalated", "order_id": order_id_val,
                           "ticket": ticket, "reason": reason})
    result = {"escalated": True, "ticket": ticket,
              "message": "A human reviewer will follow up within one business day."}
    _log_result("escalate_to_human", result)
    return result


CORE_TOOLS = {
    "lookup_customer": lookup_customer,
    "get_order": get_order,
    "get_refund_policy": get_refund_policy,
    "check_refund_eligibility": check_refund_eligibility,
    "process_refund": process_refund,
    "create_return": create_return,
    "attach_evidence": attach_evidence,
    "escalate_to_human": escalate_to_human,
}


def execute_tool(name: str, arguments: dict) -> dict:
    """Entry point used by the voice pipeline. Same functions, same logs."""
    fn = CORE_TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    try:
        return fn(**arguments)
    except TypeError as exc:
        log_event("error", {"tool": name, "error": str(exc)})
        return {"error": f"Bad arguments for {name}: {exc}"}
