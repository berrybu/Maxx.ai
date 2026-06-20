"""Cala ripple expansion engine."""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Optional

from cala import CalaClient
from graph import Edge, GraphCore, Node
from graph import schema as S

CONF_CALA_FIELD = 0.9
CONF_CALA_PERSON = 0.75

ActivityCb = Callable[[dict], None]


def _safe_id(prefix: str, text: str) -> str:
    clean = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    if not clean:
        clean = uuid.uuid4().hex[:8]
    return f"{prefix}_{clean}"


def _emit(cb: Optional[ActivityCb], status: str, message: str, **extra: Any) -> None:
    if cb is not None:
        cb({"status": status, "message": message, **extra})


def ingest_card(graph: GraphCore, card: dict[str, Any]) -> dict[str, str]:
    name = card.get("full_name") or "Unknown Contact"
    company = card.get("company") or "Unknown Company"
    person_id = _safe_id("n_person", name)
    company_id = _safe_id("n_company", company)
    graph.upsert_node(Node(id=person_id, type="person", label=name))
    graph.upsert_node(Node(id=company_id, type="company", label=company))
    graph.add_confirmed(Edge(subject=person_id, predicate=S.WORKS_AT, object=company_id,
                             source="business_card", extractor="human", confidence=1.0))
    for pred, val in [(S.JOB_TITLE, card.get("job_title")), (S.EMAIL, card.get("email")), (S.PHONE, card.get("phone"))]:
        if val:
            graph.add_confirmed(Edge(subject=person_id, predicate=pred, object=val,
                                     source="business_card", extractor="OCR", confidence=0.95))
    if card.get("country"):
        graph.add_confirmed(Edge(subject=company_id, predicate=S.COUNTRY, object=card["country"],
                                 source="business_card", extractor="OCR", confidence=0.9))
    return {"person_id": person_id, "company_id": company_id}


def _write_company_field(graph: GraphCore, company_id: str, predicate: str, value: Any) -> bool:
    if value in (None, "", []):
        return False
    existing = graph.query(subject=company_id, predicate=predicate)
    for e in existing:
        if str(e.object) == str(value) and e.status != "retired":
            return False
    graph.add_confirmed(Edge(subject=company_id, predicate=predicate, object=value,
                             source="cala", extractor="Cala", confidence=CONF_CALA_FIELD))
    return True


def enrich_from_cala(graph: GraphCore, company_id: str, *, cala: Optional[CalaClient] = None,
                     activity_cb: Optional[ActivityCb] = None) -> dict[str, Any]:
    cala = cala or CalaClient()
    company_node = graph.get_node(company_id)
    if company_node is None:
        return {"ok": False, "error": f"company not found: {company_id}"}
    company_name = company_node.label
    facts_written = 0
    _emit(activity_cb, "thinking", f"Cala is expanding the knowledge graph: locating {company_name}...")
    entities = cala.entity_search(company_name)
    company_entity = next((e for e in entities if e.get("entity_type") == "Company"), None)
    if company_entity is None and entities:
        company_entity = entities[0]
    if company_entity is None:
        _emit(activity_cb, "warn", f"Cala did not find an entity for {company_name}.")
        return {"ok": True, "company_id": company_id, "facts_written": 0,
                "cala_mock": cala.is_mock, "cala_source": cala.source}
    entity_id = company_entity.get("id")
    _emit(activity_cb, "found", f"Cala matched entity {company_entity.get('name')} ({entity_id})")
    detail = cala.retrieve_entity(entity_id) if entity_id else {}
    field_map = {"employees": S.EMPLOYEE_COUNT, "country": S.COUNTRY, "industry": S.IN_INDUSTRY,
                 "website": S.WEBSITE, "revenue": S.REVENUE, "founded_year": S.FOUNDED_YEAR}
    for cala_key, predicate in field_map.items():
        if cala_key in detail and detail[cala_key] not in (None, ""):
            if _write_company_field(graph, company_id, predicate, detail[cala_key]):
                facts_written += 1
                _emit(activity_cb, "write", f"write back: {company_name}.{predicate} = {detail[cala_key]}")
    key_people = detail.get("key_people") or []
    for kp in key_people:
        pname = kp.get("name")
        prole = kp.get("role", "")
        if not pname:
            continue
        pid = _safe_id("n_person", pname)
        if graph.get_node(pid) is None:
            graph.upsert_node(Node(id=pid, type="person", label=pname))
        already = [e for e in graph.query(subject=pid, predicate=S.WORKS_AT) if e.object == company_id and e.status != "retired"]
        if not already:
            graph.add_confirmed(Edge(subject=pid, predicate=S.WORKS_AT, object=company_id,
                                     source="cala", extractor="Cala", confidence=CONF_CALA_PERSON))
            facts_written += 1
            if prole:
                graph.add_confirmed(Edge(subject=pid, predicate=S.JOB_TITLE, object=prole,
                                         source="cala", extractor="Cala", confidence=CONF_CALA_PERSON))
            _emit(activity_cb, "write", f"merged key person {pname}({prole}) -> {company_name}")
    if detail.get("recent_news"):
        graph.upsert_node(company_node)
        graph.add_confirmed(Edge(subject=company_id, predicate="recent_news", object=detail["recent_news"],
                                 source="cala", extractor="Cala", confidence=0.8))
        facts_written += 1
        _emit(activity_cb, "write", f"wrote back latest news: {detail['recent_news'][:40]}...")
    _emit(activity_cb, "done", f"Cala expansion complete: merged {facts_written} facts into the graph.")
    return {"ok": True, "company_id": company_id, "entity_id": entity_id, "facts_written": facts_written,
            "cala_mock": cala.is_mock, "cala_source": cala.source, "cala_warning": cala.last_warning}


def scan_and_enrich(graph: GraphCore, raw_card_text: str, *, cala: Optional[CalaClient] = None,
                    activity_cb: Optional[ActivityCb] = None, use_llm: bool = True) -> dict[str, Any]:
    from extract import extract_card
    _emit(activity_cb, "scan", "Reading business card...")
    card = extract_card(raw_card_text, use_llm=use_llm)
    _emit(activity_cb, "extracted", f"Recognized: {card.get('full_name')} @ {card.get('company')} ({card.get('_method')})")
    ids = ingest_card(graph, card)
    enrich = enrich_from_cala(graph, ids["company_id"], cala=cala, activity_cb=activity_cb)
    return {"ok": True, "card": card, "person_id": ids["person_id"], "company_id": ids["company_id"], "enrichment": enrich}
