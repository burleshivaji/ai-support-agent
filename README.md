# AI Customer Support Agent

A web app where an AI agent handles refund requests for a small e-commerce
store. Customers talk to it by chat or voice. The agent verifies who they
are, checks the store refund policy with tools, and then approves, denies,
or escalates. An admin dashboard shows everything the agent does in real
time: tool calls, policy checks, decisions, retries.

Two design points worth knowing:

- The LLM never decides a refund. A plain Python policy engine
  (`backend/app/policy.py`) applies the rules in
  `backend/policy/refund_policy.md`, and every money-moving call re-checks
  the policy on the server. The agent stays polite under pressure but it
  cannot be talked into breaking a rule.
- Return refunds are not instant. Approval creates a return (RMA) with a
  ship-by date. The refund is paid when the item is marked received and
  passing inspection in the admin dashboard. Opened products need photos
  before the return is created; damaged claims always need photos. Only
  carrier fault and pre-shipment cancellations pay out right away.

## Stack

- Backend: FastAPI, LangGraph agent (agent node + tool node, per-session
  memory), OpenAI, SQLite.
- Voice: OpenAI Realtime API over WebRTC. Voice calls use the same tools
  and show up in the same logs as chat.
- Frontend: React + Vite.

## Setup

Needs Python 3.11+ and Node 18+.

Backend:

```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # add your OPENAI_API_KEY
.venv/bin/python -m app.demo
.venv/bin/uvicorn app.main:app --port 8000
```

Frontend, in a second terminal:

```
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Environment variables (backend/.env):

- `OPENAI_API_KEY` - required
- `CHAT_MODEL` - optional, default `gpt-4o-mini`
- `REALTIME_MODEL` - optional, default `gpt-realtime`

## Trying it out

Start a chat, give one of these emails, ask for a refund. Keep the admin
dashboard open in a second tab to watch the reasoning live.

| Email | Order | What happens |
|---|---|---|
| ethan.miller@example.com | ORD-1001 | Normal return: RMA created, refund after the facility marks it received |
| ethan.miller@example.com | ORD-1016 | Order not shipped yet: cancelled, refunded immediately |
| ethan.miller@example.com | ORD-1021 | Already refunded once: denied |
| olivia.turner@example.com | ORD-1004 | Final sale item: denied, agent holds the line |
| sophia.carter@example.com | ORD-1002 | VIP on day 19: split refund, half card, half store credit |
| daniel.brooks@example.com | ORD-1003 | Big spender on day 18: store credit only |
| noah.bennett@example.com | ORD-1005 | Day 40: window expired, denied |
| ava.collins@example.com | ORD-1006 | Arrived damaged: photo upload required, then RMA |
| mia.foster@example.com | ORD-1008 | Late shipment: escalated to a human |
| lucas.reed@example.com | ORD-1009 | Carrier lost it: apology and instant refund |
| james.cooper@example.com | ORD-1011 | "Never arrived" but delivery is proven: denied |
| benjamin.ward@example.com | ORD-1013 | $1,699 refund: escalated, over the $1,000 limit |
| charlotte.gray@example.com | ORD-1014 | 5 suspicious flags: blocked |
| charlotte.gray@example.com | ORD-1017 | Same customer, but carrier fault: still refunded |

Reset the demo data any time:

```
cd backend && .venv/bin/python -m app.demo
```

## Tests

```
cd backend && .venv/bin/python test_policy.py
```

Reloads the demo data and runs every scenario against the policy engine,
including the return lifecycle (refund only after facility pass, rejected
returns stay dead, opened items need photos).

## Layout

```
backend/
  app/
    main.py        API routes and the log websocket
    agent.py       LangGraph graph and LLM retry handling
    prompts.py     shared rules for the chat and voice prompts
    tools_core.py  tool implementations, shared by chat and voice
    policy.py      the refund policy engine
    realtime.py    voice session setup and tool definitions
    logbus.py      log storage and live broadcast
    demo.py        demo CRM data
    db.py          SQLite schema
  policy/refund_policy.md
  test_policy.py
frontend/
  src/components/  ChatView, VoicePanel, AdminDashboard
```
