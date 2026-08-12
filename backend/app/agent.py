"""LangGraph agent: an agent node (the LLM deciding what to do) and a tool
node (the refund tools), cycling until the agent has a final answer.
Conversation memory is checkpointed per session with MemorySaver.
"""
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition

from . import tools_core
from .logbus import log_event

from .prompts import CHAT_PROMPT as SYSTEM_PROMPT


# LangGraph-facing wrappers around the shared core tools.

@tool
def lookup_customer(email_or_phone: str) -> dict:
    """Find a customer account by the email address or phone number on the
    account. Returns the profile and all orders."""
    return tools_core.lookup_customer(email_or_phone)


@tool
def get_order(order_id: str, customer_email: str) -> dict:
    """Get full details of one order. Only works for the verified customer's own order."""
    return tools_core.get_order(order_id, customer_email)


@tool
def get_refund_policy() -> dict:
    """Return the full text of the store refund policy."""
    return tools_core.get_refund_policy()


@tool
def check_refund_eligibility(order_id: str, customer_email: str, reason: str) -> dict:
    """Run the deterministic policy engine for a refund request. Returns
    APPROVE, DENY, or ESCALATE with the rule and explanation. Must be called
    before promising anything."""
    return tools_core.check_refund_eligibility(order_id, customer_email, reason)


@tool
def process_refund(order_id: str, customer_email: str, reason: str) -> dict:
    """Execute an immediately-payable refund (carrier fault or pre-shipment
    cancellation only). Re-validates policy first. Return-type refunds must
    use create_return instead."""
    return tools_core.process_refund(order_id, customer_email, reason)


@tool
def create_return(order_id: str, customer_email: str, reason: str, opened: bool) -> dict:
    """Create a return (RMA) for an approved return-type refund. The refund is
    issued only after the item reaches the facility and passes inspection.
    Set opened=true if the customer says the product was opened or used; opened
    products require an uploaded photo (attach_evidence) first."""
    return tools_core.create_return(order_id, customer_email, reason, opened)


@tool
def attach_evidence(order_id: str, customer_email: str, filename: str = "") -> dict:
    """Link a photo the customer uploaded in chat to their order. Leave
    filename empty to use their most recent upload in this conversation."""
    return tools_core.attach_evidence(order_id, customer_email, filename)


@tool
def escalate_to_human(order_id: str, customer_email: str, reason: str) -> dict:
    """Open a ticket for a human reviewer when the policy requires escalation."""
    return tools_core.escalate_to_human(order_id, customer_email, reason)


TOOLS = [lookup_customer, get_order, get_refund_policy,
         check_refund_eligibility, process_refund, create_return,
         attach_evidence, escalate_to_human]

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        model = os.getenv("CHAT_MODEL", "gpt-4o-mini")
        _llm = ChatOpenAI(model=model, temperature=0).bind_tools(TOOLS)
    return _llm


def agent_node(state: MessagesState):
    """One LLM step, with retry on transient API failures."""
    messages = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    last_error = None
    for attempt in range(1, 4):
        try:
            response = _get_llm().invoke(messages)
            break
        except Exception as exc:
            last_error = exc
            log_event("retry", {"stage": "llm_call", "attempt": attempt,
                                "error": str(exc)[:300]})
            time.sleep(min(2 ** attempt, 8))
    else:
        log_event("error", {"stage": "llm_call", "error": str(last_error)[:300]})
        raise last_error

    if response.tool_calls:
        log_event("assistant_message", {
            "kind": "tool_request",
            "tools": [{"name": t["name"], "args": t["args"]} for t in response.tool_calls],
        })
    return {"messages": [response]}


def build_graph():
    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=MemorySaver())


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_turn(session_id: str, user_message: str) -> str:
    """Run one conversation turn. Called from a worker thread; the logbus
    context vars are already set by the endpoint."""
    log_event("user_message", {"text": user_message})
    result = get_graph().invoke(
        {"messages": [HumanMessage(user_message)]},
        config={"configurable": {"thread_id": session_id}, "recursion_limit": 30},
    )
    reply = result["messages"][-1].content
    log_event("assistant_message", {"kind": "final", "text": reply})
    return reply
