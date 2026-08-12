"""Log bus: every agent step is written to SQLite and pushed to any
connected admin dashboards over WebSocket. Works from sync tool code
running in a worker thread by handing the broadcast to the main loop.
"""
import asyncio
import contextvars
import json
from datetime import datetime, timezone

from .db import get_conn

# Set per request so tools know which conversation they belong to.
current_session = contextvars.ContextVar("current_session", default="unknown")
current_channel = contextvars.ContextVar("current_channel", default="chat")

_main_loop: asyncio.AbstractEventLoop | None = None
_listeners: set = set()


def attach_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


def add_listener(ws):
    _listeners.add(ws)


def remove_listener(ws):
    _listeners.discard(ws)


async def _broadcast(event: dict):
    dead = []
    for ws in list(_listeners):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _listeners.discard(ws)


def log_event(event_type: str, content: dict):
    """Persist one agent log row and broadcast it live. Safe to call from
    any thread."""
    event = {
        "session_id": current_session.get(),
        "channel": current_channel.get(),
        "type": event_type,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO agent_logs (session_id, channel, type, content, created_at) VALUES (?,?,?,?,?)",
        (event["session_id"], event["channel"], event_type,
         json.dumps(content), event["created_at"]),
    )
    conn.commit()
    conn.close()
    event["id"] = cur.lastrowid

    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(event), _main_loop)
    return event
