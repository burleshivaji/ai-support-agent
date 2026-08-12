"""Voice pipeline glue for the OpenAI Realtime API.

The browser talks to the Realtime model directly over WebRTC. This module
only mints a short-lived client secret (so the real API key never reaches
the browser) and defines the same refund tools for the voice session.
Tool calls from the voice session are executed by POST /api/realtime/tool,
which runs the exact same core functions and logging as the chat agent.
"""
import os

import httpx

from .prompts import VOICE_PROMPT as VOICE_INSTRUCTIONS

TOOL_DEFS = [
    {
        "type": "function",
        "name": "lookup_customer",
        "description": "Find a customer account by email address or phone number. Returns profile and orders.",
        "parameters": {
            "type": "object",
            "properties": {"email_or_phone": {"type": "string"}},
            "required": ["email_or_phone"],
        },
    },
    {
        "type": "function",
        "name": "get_order",
        "description": "Get full details of one order belonging to the verified customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
            },
            "required": ["order_id", "customer_email"],
        },
    },
    {
        "type": "function",
        "name": "get_refund_policy",
        "description": "Return the full refund policy text.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "check_refund_eligibility",
        "description": "Run the deterministic refund policy engine. Returns APPROVE, DENY, or ESCALATE.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "reason": {"type": "string",
                           "enum": ["CHANGE_OF_MIND", "DAMAGED_OR_DEFECTIVE", "NOT_RECEIVED",
                                    "STOLEN_AFTER_DELIVERY", "CANCEL_BEFORE_SHIP",
                                    "LATE_SHIPMENT", "OTHER"]},
            },
            "required": ["order_id", "customer_email", "reason"],
        },
    },
    {
        "type": "function",
        "name": "process_refund",
        "description": "Execute a refund the policy engine approved. Re-validates before moving money.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "customer_email", "reason"],
        },
    },
    {
        "type": "function",
        "name": "create_return",
        "description": "Create a return (RMA) for an approved return-type refund. Refund is issued after facility inspection. Opened products need an uploaded photo first.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "reason": {"type": "string"},
                "opened": {"type": "boolean"},
            },
            "required": ["order_id", "customer_email", "reason", "opened"],
        },
    },
    {
        "type": "function",
        "name": "attach_evidence",
        "description": "Link a photo the customer uploaded in the chat page to their order. Omit filename to use their most recent upload.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "filename": {"type": "string"},
            },
            "required": ["order_id", "customer_email"],
        },
    },
    {
        "type": "function",
        "name": "escalate_to_human",
        "description": "Open a ticket for a human reviewer.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "customer_email": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "customer_email", "reason"],
        },
    },
]


async def create_client_secret() -> dict:
    """Mint an ephemeral Realtime session key for the browser."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY is not set on the server."}
    model = os.getenv("REALTIME_MODEL", "gpt-realtime")
    payload = {
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": VOICE_INSTRUCTIONS,
            "tools": TOOL_DEFS,
            "audio": {"output": {"voice": "marin"}},
        }
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    if resp.status_code >= 400:
        return {"error": f"OpenAI returned {resp.status_code}: {resp.text[:300]}"}
    data = resp.json()
    return {"client_secret": data.get("value"), "model": model}
