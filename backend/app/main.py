import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import re
import time

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import logbus, realtime, tools_core
from .agent import run_turn
from .db import get_conn, init_db, DB_PATH

app = FastAPI(title="AI Customer Support Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    if not DB_PATH.exists():
        from .demo import load_demo_data
        load_demo_data()
    else:
        init_db()
    logbus.attach_loop(asyncio.get_running_loop())


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    logbus.current_session.set(req.session_id)
    logbus.current_channel.set("chat")
    try:
        reply = await asyncio.to_thread(run_turn, req.session_id, req.message)
    except Exception as exc:
        logbus.log_event("error", {"stage": "chat_turn", "error": str(exc)[:300]})
        return {"reply": "Sorry, something went wrong on our side. Please try again.",
                "error": str(exc)[:300]}
    return {"reply": reply}


class ToolRequest(BaseModel):
    session_id: str
    name: str
    arguments: dict = {}


@app.post("/api/realtime/tool")
async def realtime_tool(req: ToolRequest):
    """Tool execution for the voice pipeline. Same core tools, same logs."""
    logbus.current_session.set(req.session_id)
    logbus.current_channel.set("voice")
    result = await asyncio.to_thread(tools_core.execute_tool, req.name, req.arguments)
    return {"result": result}


@app.post("/api/upload")
async def upload(session_id: str = Form(...), file: UploadFile = File(...)):
    """Damage photo upload from the chat. The agent links it to an order
    with the attach_evidence tool afterwards."""
    logbus.current_session.set(session_id)
    logbus.current_channel.set("chat")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "photo")
    stored = f"{int(time.time())}_{base}"
    dest = tools_core.UPLOAD_DIR / stored
    dest.write_bytes(await file.read())
    conn = get_conn()
    conn.execute(
        "INSERT INTO evidence (order_id, customer_id, filename, session_id, uploaded_at) "
        "VALUES (NULL, NULL, ?, ?, ?)",
        (stored, session_id, tools_core._now()))
    conn.commit()
    conn.close()
    logbus.log_event("tool_result", {"tool": "photo_upload",
                                     "result": {"stored_as": stored,
                                                "size_bytes": dest.stat().st_size}})
    return {"stored_as": stored}


@app.post("/api/realtime/session")
async def realtime_session():
    return await realtime.create_client_secret()


@app.get("/api/policy")
async def policy():
    return {"policy": tools_core.POLICY_PATH.read_text()}


@app.get("/api/customers")
async def customers():
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id) AS order_count "
        "FROM customers c ORDER BY c.id").fetchall()
    conn.close()
    return {"customers": [dict(r) for r in rows]}


@app.get("/api/orders")
async def orders():
    conn = get_conn()
    rows = conn.execute(
        "SELECT o.*, c.name AS customer_name FROM orders o "
        "JOIN customers c ON c.id = o.customer_id ORDER BY o.id").fetchall()
    conn.close()
    return {"orders": [dict(r) for r in rows]}


@app.get("/api/returns")
async def returns():
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, c.name AS customer_name, o.item FROM returns r "
        "JOIN customers c ON c.id = r.customer_id "
        "JOIN orders o ON o.id = r.order_id ORDER BY r.id DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["refund_plan"] = json.loads(d["refund_plan"])
        out.append(d)
    return {"returns": out}


class ResolveRequest(BaseModel):
    outcome: str  # pass | fail


@app.post("/api/returns/{return_id}/resolve")
async def resolve_return(return_id: int, req: ResolveRequest):
    """Facility inspection result, triggered from the admin dashboard."""
    logbus.current_session.set("facility")
    logbus.current_channel.set("admin")
    result = await asyncio.to_thread(tools_core.resolve_return, return_id, req.outcome)
    return result


@app.get("/api/refunds")
async def refunds():
    conn = get_conn()
    rows = conn.execute(
        "SELECT r.*, c.name AS customer_name FROM refunds r "
        "JOIN customers c ON c.id = r.customer_id ORDER BY r.id DESC").fetchall()
    conn.close()
    return {"refunds": [dict(r) for r in rows]}


@app.get("/api/escalations")
async def escalations():
    conn = get_conn()
    rows = conn.execute(
        "SELECT e.*, c.name AS customer_name FROM escalations e "
        "LEFT JOIN customers c ON c.id = e.customer_id ORDER BY e.id DESC").fetchall()
    conn.close()
    return {"escalations": [dict(r) for r in rows]}


@app.get("/api/logs")
async def logs(limit: int = 200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    out = []
    for r in reversed(rows):
        d = dict(r)
        d["content"] = json.loads(d["content"])
        out.append(d)
    return {"logs": out}


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await ws.accept()
    logbus.add_listener(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from the client
    except WebSocketDisconnect:
        pass
    finally:
        logbus.remove_listener(ws)
