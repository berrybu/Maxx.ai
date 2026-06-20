"""Email Agent -- reads technical docs (RAG) + graph context + long-term memory, composes and sends via MCP."""

from __future__ import annotations

from typing import Any, Optional

from config import get_settings
from graph import GraphCore
from graph import schema as S
from llm import OllamaUnavailable, chat, chat_with_tools
from agent import memory, rag
from agent.mcp_bridge import send_email_via_mcp

SEND_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "Send an email to a prospect. Call this when the email body is ready and needs to be actually sent.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "recipient email address"},
                "subject": {"type": "string", "description": "email subject"},
                "body": {"type": "string", "description": "email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
}


def _gather_context(graph: GraphCore, person_id: str) -> dict[str, Any]:
    person = graph.get_node(person_id)
    if person is None:
        return {}
    name = person.label
    email = graph.prop(person_id, S.EMAIL)
    title = graph.prop(person_id, S.JOB_TITLE)
    company_id = None
    for e in graph.query(subject=person_id, predicate=S.WORKS_AT):
        if e.status != "retired":
            company_id = e.object
            break
    company_facts = {}
    company_name = None
    if company_id:
        cnode = graph.get_node(company_id)
        company_name = cnode.label if cnode else company_id
        for pred in (S.EMPLOYEE_COUNT, S.COUNTRY, S.IN_INDUSTRY, S.REVENUE, S.WEBSITE, "recent_news"):
            val = graph.prop(company_id, pred)
            if val is not None:
                company_facts[pred] = val
    return {"person_id": person_id, "name": name, "email": email, "title": title,
            "company_id": company_id, "company_name": company_name, "company_facts": company_facts}


_COMPOSE_SYSTEM = (
    "You are {name}, a senior B2B sales manager at {company} ({desc}). "
    "Your task: based on our product technical docs and the prospect's profile, "
    "write a highly personalized, professional, concise cold email. Requirements:\n"
    "1) Open with a hook based on the prospect company's latest news / industry background;\n"
    "2) Connect the prospect's business pain points with our specific product capabilities (cite specs / value propositions from the doc);\n"
    "3) End with a light CTA (a brief call);\n"
    "4) Output should include a Subject line and a body. Use the same language as the customer (default English)."
)


def _compose_system():
    s = get_settings()
    return _COMPOSE_SYSTEM.format(company=s.seller_company, desc=s.seller_desc, name=s.seller_name)


def compose_email(graph: GraphCore, person_id: str) -> dict[str, Any]:
    ctx = _gather_context(graph, person_id)
    if not ctx:
        return {"ok": False, "error": f"contact does not exist: {person_id}"}
    rag_query = f"{ctx.get('company_name','')} {ctx.get('title','')} {ctx['company_facts'].get(S.IN_INDUSTRY,'')}"
    product_ctx = rag.retrieve(rag_query, k=3)
    user_prompt = (
        f"### Our product doc (excerpt)\n{product_ctx}\n\n"
        f"### Prospect profile\n"
        f"Name: {ctx.get('name')}\nTitle: {ctx.get('title')}\nCompany: {ctx.get('company_name')}\n"
        f"Company facts: {ctx.get('company_facts')}\n\n"
        f"Please write this cold email. Give the subject on the first line as 'Subject: ...'."
    )
    try:
        draft = chat([
            {"role": "system", "content": _compose_system()},
            {"role": "user", "content": user_prompt},
        ])
    except OllamaUnavailable as e:
        draft = _fallback_draft(ctx, product_ctx)
        subject, body = _split_subject(draft)
        return {"ok": True, "subject": subject, "body": body, "context": ctx, "llm": False, "note": str(e)}
    subject, body = _split_subject(draft)
    return {"ok": True, "subject": subject, "body": body, "context": ctx, "llm": True}


def compose_and_send(graph: GraphCore, person_id: str, *, use_agent_tool: bool = True, subject: str | None = None, body: str | None = None) -> dict[str, Any]:
    drafted = compose_email(graph, person_id)
    if not drafted.get("ok"):
        return drafted
    if subject is not None and str(subject).strip():
        drafted["subject"] = subject
    if body is not None and str(body).strip():
        drafted["body"] = body
    ctx = drafted["context"]
    to = ctx.get("email")
    if not to:
        return {"ok": False, "error": f"{ctx.get('name')} has no email, cannot send", "draft": drafted}
    thread_id = memory.get_or_create_thread(graph, ctx["company_id"], about_person_id=person_id, employee=get_settings().seller_name)
    tool_records: list[dict] = []
    if use_agent_tool:
        def executor(name: str, args: dict) -> Any:
            if name == "send_email":
                return send_email_via_mcp(args["to"], args["subject"], args["body"])
            return {"error": f"unknown tool {name}"}
        agent_prompt = (f"Here is the finished email draft, please call the send_email tool to send it to {to}.\n\n"
                        f"Subject: {drafted['subject']}\n\n{drafted['body']}")
        try:
            out = chat_with_tools(
                [{"role": "system", "content": "You are a sales assistant responsible for calling tools to send the email."},
                 {"role": "user", "content": agent_prompt}],
                tools=[SEND_EMAIL_TOOL], tool_executor=executor)
            tool_records = out["tool_calls"]
            sent = next((r for r in tool_records if r["name"] == "send_email" and r.get("ok")), None)
            send_result = sent["result"] if sent else {"ok": False, "error": "LLM did not call the send tool"}
        except OllamaUnavailable:
            send_result = send_email_via_mcp(to, drafted["subject"], drafted["body"])
    else:
        send_result = send_email_via_mcp(to, drafted["subject"], drafted["body"])
    if send_result.get("ok"):
        memory.record_message(graph, thread_id, direction="outbound",
                              subject=drafted["subject"], body=drafted["body"], employee=get_settings().seller_name)
    return {"ok": bool(send_result.get("ok")), "draft": drafted, "send_result": send_result,
            "tool_calls": tool_records, "thread_id": thread_id}


_REPLY_SYSTEM = (
    "You are {name}, a sales manager at {company}. The customer has replied to your email. "
    "Based on the full conversation history and the product doc, write a professional, "
    "deal-advancing reply: answer the customer's questions, add relevant product information, "
    "and propose a next step (e.g. schedule a call or send samples). "
    "Use 'Subject: ...' on the first line."
)


def _reply_system():
    s = get_settings()
    return _REPLY_SYSTEM.format(company=s.seller_company, name=s.seller_name)


def handle_inbound_reply(graph: GraphCore, thread_id: str, inbound_body: str, *,
                         inbound_subject: str = "Re:", auto_send: bool = True) -> dict[str, Any]:
    memory.record_message(graph, thread_id, direction="inbound",
                          subject=inbound_subject, body=inbound_body, employee=get_settings().seller_name)
    summary = memory.thread_summary(graph, thread_id)
    history = summary["messages"]
    to = _thread_recipient_email(graph, thread_id)
    history_text = "\n\n".join(f"[{m['direction']}] {m.get('subject','')}\n{m.get('body','')}" for m in history)
    product_ctx = rag.retrieve(inbound_body, k=2)
    try:
        draft = chat([
            {"role": "system", "content": _reply_system()},
            {"role": "user", "content":
                f"### Product doc (excerpt)\n{product_ctx}\n\n"
                f"### Full conversation history\n{history_text}\n\n"
                f"### Customer's latest reply\n{inbound_body}\n\nPlease write the reply."}])
        llm_used = True
    except OllamaUnavailable as e:
        draft = (f"Subject: Re: {inbound_subject}\n\nHi,\n\nThanks for your reply. (LLM offline, using a template) "
                 f"We can arrange a brief call to discuss further.\n\nBest,\n{get_settings().seller_name} — {get_settings().seller_company}")
        llm_used = False
    subject, body = _split_subject(draft)
    send_result = None
    if auto_send and to:
        send_result = send_email_via_mcp(to, subject, body)
        if send_result.get("ok"):
            memory.record_message(graph, thread_id, direction="outbound",
                                  subject=subject, body=body, employee=get_settings().seller_name)
    return {"ok": True, "reply_subject": subject, "reply_body": body, "send_result": send_result,
            "llm": llm_used, "thread_summary": memory.thread_summary(graph, thread_id)}


# ============================================================================
# Session management: a "session" == one email_thread. After a cold email is
# sent the thread exists; when a customer replies the agent AUTO-DRAFTS the next
# email but does NOT send it -- stored as pending_reply, waiting for a human to
# confirm before sending.
# ============================================================================

def _session_view(graph: GraphCore, thread_id: str) -> dict[str, Any]:
    """Build a UI-friendly view of one session (thread)."""
    summary = memory.thread_summary(graph, thread_id)

    company_name = None
    for e in graph.query(predicate=S.HAS_EMAIL_THREAD, object=thread_id):
        if e.status != "retired":
            c = graph.get_node(e.subject)
            company_name = c.label if c else e.subject
            break

    person_id = person_name = person_email = None
    for e in graph.query(subject=thread_id, predicate=S.ABOUT_PERSON):
        if e.status != "retired":
            person_id = e.object
            p = graph.get_node(person_id)
            person_name = p.label if p else person_id
            person_email = graph.prop(person_id, S.EMAIL)
            break

    msgs = summary["messages"]
    pending = graph.prop(thread_id, S.PENDING_REPLY, default=None)
    return {
        "thread_id": thread_id,
        "company": company_name,
        "person_id": person_id,
        "person": person_name,
        "email": person_email,
        "status": summary["status"],
        "message_count": summary["message_count"],
        "last_contact": summary["last_contact"],
        "last_t": msgs[-1]["t"] if msgs else 0,
        "pending_reply": pending if isinstance(pending, dict) else None,
        "messages": msgs,
    }


def list_sessions(graph: GraphCore) -> dict[str, Any]:
    """List every email session (thread), newest activity first."""
    sessions = [_session_view(graph, t.id) for t in graph.list_nodes(node_type="email_thread")]
    sessions.sort(key=lambda s: s.get("last_t", 0), reverse=True)
    return {"ok": True, "count": len(sessions), "sessions": sessions}


def session_detail(graph: GraphCore, thread_id: str) -> dict[str, Any]:
    return _session_view(graph, thread_id)


def draft_reply(graph: GraphCore, thread_id: str, inbound_body: str, *,
                inbound_subject: str = "Re:") -> dict[str, Any]:
    """Customer reply received -> record inbound -> AI drafts the next email but
    does NOT send it. Draft stored as pending_reply for human confirmation."""
    res = handle_inbound_reply(graph, thread_id, inbound_body,
                               inbound_subject=inbound_subject, auto_send=False)
    pending = {"subject": res["reply_subject"], "body": res["reply_body"]}
    memory._set_thread_field(graph, thread_id, S.PENDING_REPLY, pending)
    return {"ok": True, "thread_id": thread_id,
            "inbound": {"subject": inbound_subject, "body": inbound_body},
            "draft": pending, "llm": res["llm"],
            "session": _session_view(graph, thread_id)}


def send_reply(graph: GraphCore, thread_id: str, subject: str, body: str) -> dict[str, Any]:
    """Human confirmed the AI draft -> send it (mock/MCP), record outbound, clear pending."""
    to = _thread_recipient_email(graph, thread_id)
    if not to:
        return {"ok": False, "error": "this session has no recipient email"}
    send_result = send_email_via_mcp(to, subject, body)
    if send_result.get("ok"):
        memory.record_message(graph, thread_id, direction="outbound",
                              subject=subject, body=body, employee=get_settings().seller_name)
        memory._set_thread_field(graph, thread_id, S.PENDING_REPLY, None)
    return {"ok": bool(send_result.get("ok")), "send_result": send_result,
            "session": _session_view(graph, thread_id)}


def _split_subject(draft: str):
    lines = draft.strip().splitlines()
    subject = f"{get_settings().seller_company} — Partnership inquiry"
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip()
    return subject, body or draft.strip()


def _fallback_draft(ctx: dict, product_ctx: str) -> str:
    s = get_settings()
    news = ctx["company_facts"].get("recent_news", "")
    hook = f"I noticed {ctx.get('company_name')} {news}" if news else f"I've been following {ctx.get('company_name')}"
    return (f"Subject: Partnership opportunity for {ctx.get('company_name')}\n\n"
            f"Hi {ctx.get('name','there')},\n\n"
            f"{hook}. At {s.seller_company} we help customers like you with our product "
            f"line and would value a short conversation to explore a fit.\n\n"
            f"Would you be open to a brief 10-minute call?\n\n"
            f"Best,\n{s.seller_name} — {s.seller_company}")


def _thread_recipient_email(graph: GraphCore, thread_id: str) -> Optional[str]:
    for e in graph.query(subject=thread_id, predicate=S.ABOUT_PERSON):
        if e.status != "retired":
            return graph.prop(e.object, S.EMAIL)
    return None
