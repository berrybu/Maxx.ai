"""Maxx FastAPI backend -- wires the whole pipeline together and serves the frontend."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cala import CalaClient
from graph import GraphCore
from graph import schema as S
from enrich import scan_and_enrich, enrich_from_cala
from extract import get_sample_card_text, SAMPLE_CARDS, ocr_image
from query import run_targeting, scout_customers, filter_network
from agent import email_agent, memory
from seed import seed_data

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = os.path.join(_ROOT, "graph_store.json")
_WEB = os.path.join(_ROOT, "web")

app = FastAPI(title="Maxx — Automotive Parts Sales OS", version="0.1")

graph = GraphCore(store_path=_STORE)
if not graph.load():
    seed_data.load_into(graph)

class ScanBody(BaseModel):
    card_key: Optional[str] = None
    raw_text: Optional[str] = None
    use_llm: bool = False
    image_b64: Optional[str] = None
    image_mime: str = "image/jpeg"


class PersonBody(BaseModel):
    person_id: str
    use_agent_tool: bool = True
    subject: Optional[str] = None
    body: Optional[str] = None


class ReplyBody(BaseModel):
    thread_id: str
    inbound_body: str
    inbound_subject: str = "Re:"
    auto_send: bool = True


class TargetBody(BaseModel):
    text: str


class CampaignBody(BaseModel):
    text: str
    use_agent_tool: bool = False
    limit: int = 10


class MockReplyBody(BaseModel):
    inbound_body: Optional[str] = None
    inbound_subject: str = "Re: your email"


class SendReplyBody(BaseModel):
    subject: str
    body: str


class StageBody(BaseModel):
    stage: str


# Simulated customer-reply corpus (used to mock incoming replies, triggers AI auto-drafting)
_MOCK_REPLIES = [
    "Hi Tim, thanks for reaching out. We are indeed evaluating new suppliers for our "
    "next-gen platform. Could you share PPM quality data, lead times and whether you "
    "support IATF 16949?",
    "Hello, interesting timing — our current supplier has had delivery issues. "
    "What MOQ and pricing tiers can you offer, and do you have automotive references?",
    "Thanks Tim. Before a call, can you send a short capability deck and confirm you "
    "can meet 800V / high-temperature requirements?",
]


@app.get("/api/health")
def health() -> dict:
    cala = CalaClient()
    return {"status": "ok", "cala_mock": cala.is_mock, "cala_source": cala.source, "cala_warning": cala.last_warning}


@app.get("/api/graph")
def get_graph() -> dict:
    return graph.snapshot()


@app.get("/api/samples")
def samples() -> dict:
    return {"cards": list(SAMPLE_CARDS.keys())}


@app.post("/api/scan")
def scan(body: ScanBody) -> dict:
    ocr_text = None
    use_llm = body.use_llm
    if body.image_b64:
        try:
            ocr_text = ocr_image(body.image_b64, mime=body.image_mime)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"OCR failed: {e}")
        raw = ocr_text
        use_llm = True
    else:
        raw = body.raw_text or get_sample_card_text(body.card_key or "bosch")
    events: list[dict] = []
    cala = CalaClient()
    res = scan_and_enrich(graph, raw, cala=cala, activity_cb=lambda e: events.append(e), use_llm=use_llm)
    return {
        "ok": res["ok"],
        "card": res["card"],
        "person_id": res["person_id"],
        "company_id": res["company_id"],
        "activity": events,
        "facts_written": res["enrichment"].get("facts_written", 0),
        "cala_mock": res["enrichment"].get("cala_mock"),
        "cala_source": res["enrichment"].get("cala_source"),
        "ocr_text": ocr_text,
    }



@app.post("/api/mail/compose")
def mail_compose(body: PersonBody) -> dict:
    res = email_agent.compose_email(graph, body.person_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/mail/send")
def mail_send(body: PersonBody) -> dict:
    res = email_agent.compose_and_send(
        graph, body.person_id, use_agent_tool=body.use_agent_tool,
        subject=body.subject, body=body.body,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "send failed"))
    return res


@app.post("/api/mail/reply")
def mail_reply(body: ReplyBody) -> dict:
    res = email_agent.handle_inbound_reply(
        graph, body.thread_id, body.inbound_body,
        inbound_subject=body.inbound_subject, auto_send=body.auto_send,
    )
    return res


# ---- Session management (a session is created when a cold email is sent; on reply -> AI auto-drafts -> awaits human confirmation to send) ----
@app.get("/api/sessions")
def sessions_list() -> dict:
    """List all email sessions (threads), including each session's conversation history and the pending AI draft."""
    return email_agent.list_sessions(graph)


@app.delete("/api/sessions")
def sessions_clear() -> dict:
    """Clear all email sessions (threads) and their message history from the graph."""
    threads = [t.id for t in graph.list_nodes(node_type="email_thread")]
    for tid in threads:
        graph.delete_node(tid)
    return {"ok": True, "cleared": len(threads)}


@app.get("/api/sessions/{thread_id}")
def session_get(thread_id: str) -> dict:
    if graph.get_node(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"session not found: {thread_id}")
    return email_agent.session_detail(graph, thread_id)


@app.post("/api/sessions/{thread_id}/mock_reply")
def session_mock_reply(thread_id: str, body: MockReplyBody) -> dict:
    """Simulate receiving a customer reply -> record inbound -> AI auto-drafts a response (does not send, awaits human confirmation)."""
    if graph.get_node(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"session not found: {thread_id}")
    import random

    text = body.inbound_body or random.choice(_MOCK_REPLIES)
    return email_agent.draft_reply(graph, thread_id, text, inbound_subject=body.inbound_subject)


@app.post("/api/sessions/{thread_id}/send_reply")
def session_send_reply(thread_id: str, body: SendReplyBody) -> dict:
    """Send after a human confirms the AI draft (mock/MCP), and write to long-term memory."""
    if graph.get_node(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"session not found: {thread_id}")
    res = email_agent.send_reply(graph, thread_id, body.subject, body.body)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "send failed"))
    return res


@app.post("/api/target")
def target(body: TargetBody) -> dict:
    cala = CalaClient()
    return run_targeting(graph, body.text, cala=cala)


@app.post("/api/scout")
def scout(body: TargetBody) -> dict:
    cala = CalaClient()
    return scout_customers(body.text, cala=cala, graph=graph)


@app.post("/api/filter")
def filter_contacts(body: TargetBody) -> dict:
    return filter_network(graph, body.text)


@app.post("/api/campaign")
def campaign(body: CampaignBody) -> dict:
    cala = CalaClient()
    tgt = run_targeting(graph, body.text, cala=cala)
    sent = []
    for person in tgt["targets"][: body.limit]:
        if not person.get("email"):
            sent.append({"person": person["name"], "ok": False, "error": "no email"})
            continue
        r = email_agent.compose_and_send(graph, person["person_id"], use_agent_tool=body.use_agent_tool)
        sent.append({
            "person": person["name"],
            "ok": r.get("ok"),
            "subject": r.get("draft", {}).get("subject"),
            "send_mode": r.get("send_result", {}).get("mode"),
            "transport": r.get("send_result", {}).get("transport"),
        })
    return {"ok": True, "targeting": tgt, "sent": sent, "sent_count": len(sent)}


@app.get("/api/outbox")
def outbox() -> dict:
    import json

    path = os.path.join(_ROOT, "outbox.json")
    if not os.path.exists(path):
        return {"emails": []}
    with open(path, "r", encoding="utf-8") as f:
        return {"emails": json.load(f)}


@app.get("/api/deals")
def deals() -> dict:
    """Return the sales pipeline as flat rows for the Attio-style grid."""
    strength_by_stage = {
        "won": "very_strong", "qualified": "strong", "quoted": "good",
        "lead": "weak", "lost": "very_weak",
    }
    rows = []
    for d in graph.list_nodes(node_type="deal"):
        comp_edges = graph.query(predicate=S.HAS_DEAL, object=d.id)
        company_id = comp_edges[0].subject if comp_edges else None
        company = graph.get_node(company_id) if company_id else None
        stage = graph.prop(d.id, S.DEAL_STAGE, default="lead")
        value = graph.prop(d.id, S.DEAL_VALUE, default=None)
        contact_id = graph.prop(d.id, S.ABOUT_PERSON, default=None)
        contact = graph.get_node(contact_id) if contact_id else None
        contact_email = graph.prop(contact_id, S.EMAIL, default=None) if contact_id else None
        owner_id = graph.prop(d.id, S.WON_BY, default=None)
        owner = graph.get_node(owner_id) if owner_id else None
        strength = graph.prop(d.id, S.CONNECTION_STRENGTH, default=strength_by_stage.get(stage, "weak"))
        next_step = graph.prop(d.id, S.NEXT_STEP, default=None)
        rows.append({
            "deal_id": d.id,
            "company": company.label if company else "?",
            "company_id": company_id,
            "industry": graph.prop(company_id, S.IN_INDUSTRY) if company_id else None,
            "country": graph.prop(company_id, S.COUNTRY) if company_id else None,
            "employees": graph.prop(company_id, S.EMPLOYEE_COUNT) if company_id else None,
            "stage": stage,
            "value": value,
            "contact": contact.label if contact else None,
            "contact_id": contact_id,
            "contact_email": contact_email,
            "owner": owner.label if owner else None,
            "connection_strength": strength,
            "next_step": next_step,
        })
    order = {"won": 0, "qualified": 1, "quoted": 2, "lead": 3, "lost": 4}
    rows.sort(key=lambda r: (order.get(r["stage"], 9), r["company"]))
    return {"deals": rows, "stages": list(S.DEAL_STAGES)}


@app.post("/api/deals/{deal_id}/stage")
def deal_set_stage(deal_id: str, body: StageBody) -> dict:
    """Inline-edit a deal's stage from the grid (Attio-style), persisted to the graph."""
    if graph.get_node(deal_id) is None:
        raise HTTPException(status_code=404, detail=f"deal not found: {deal_id}")
    if body.stage not in S.DEAL_STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of {S.DEAL_STAGES}")
    from graph import Edge
    graph.add_confirmed(Edge(subject=deal_id, predicate=S.DEAL_STAGE, object=body.stage,
                             source="crm", extractor="human", confidence=1.0))
    return {"ok": True, "deal_id": deal_id, "stage": body.stage}


if os.path.isdir(os.path.join(_WEB, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(_WEB, "static")), name="static")


@app.get("/")
def index() -> FileResponse:
    idx = os.path.join(_WEB, "index.html")
    if not os.path.exists(idx):
        raise HTTPException(status_code=404, detail="frontend not built")
    return FileResponse(idx)
