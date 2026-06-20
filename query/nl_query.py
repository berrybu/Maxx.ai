"""Natural-language targeting query."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from cala import CalaClient
from graph import GraphCore
from graph import schema as S
from llm import OllamaUnavailable, chat_json

_PARSE_SYSTEM = (
    "You are a query parser. Parse the user's natural-language targeting instruction into JSON, with fields: "
    "cala_input, country, industry, min_employees, crm_employee, crm_min_messages. Output JSON only."
)


def parse_query(text: str) -> dict[str, Any]:
    try:
        parsed = chat_json([{"role": "system", "content": _PARSE_SYSTEM}, {"role": "user", "content": text}])
        parsed["_method"] = "ollama"
        return parsed
    except (OllamaUnavailable, json.JSONDecodeError, Exception):
        return _heuristic_parse(text)


def _heuristic_parse(text: str) -> dict[str, Any]:
    t = text
    country = "Germany" if re.search(r"german", t, re.I) else None
    industry = "automotive" if re.search(r"automotive|car", t, re.I) else None
    min_emp = None
    m = re.search(r"employee[s]?\D*(\d{3,})", t, re.I)
    if not m:
        m = re.search(r">\s*(\d{3,})", t)
    if m:
        min_emp = int(m.group(1))
    crm_emp = None
    m2 = re.search(r"([A-Z][a-z]+)\s+sent", t)
    if m2:
        crm_emp = m2.group(1)
    elif re.search(r"\bTim\b", t):
        crm_emp = "Tim"
    min_msg = None
    m3 = re.search(r"sent\D*(\d+)", t, re.I)
    if m3:
        min_msg = int(m3.group(1))
    cala_parts = []
    if industry:
        cala_parts.append(f"{industry} companies")
    if country:
        cala_parts.append(f"in {country}")
    if min_emp:
        cala_parts.append(f"with more than {min_emp} employees")
    cala_input = " ".join(cala_parts) or text
    return {"cala_input": cala_input, "country": country, "industry": industry, "min_employees": min_emp,
            "crm_employee": crm_emp, "crm_min_messages": min_msg, "_method": "heuristic"}


def _company_passes_crm(graph: GraphCore, company_id: str, employee: Optional[str], min_messages: Optional[int]) -> bool:
    if not employee and not min_messages:
        return True
    for e in graph.query(subject=company_id, predicate=S.HAS_EMAIL_THREAD):
        if e.status == "retired":
            continue
        thread_id = e.object
        emp = graph.prop(thread_id, S.SENT_BY_EMPLOYEE)
        count = int(graph.prop(thread_id, S.MESSAGE_COUNT, default=0) or 0)
        if employee and (emp or "").lower() != employee.lower():
            continue
        if min_messages and count < min_messages:
            continue
        return True
    return False


def _people_at_company(graph: GraphCore, company_id: str) -> list[dict]:
    people = []
    for e in graph.query(predicate=S.WORKS_AT, object=company_id):
        if e.status == "retired":
            continue
        pnode = graph.get_node(e.subject)
        if pnode is None or pnode.type != "person":
            continue
        people.append({"person_id": pnode.id, "name": pnode.label,
                       "email": graph.prop(pnode.id, S.EMAIL), "title": graph.prop(pnode.id, S.JOB_TITLE)})
    return people


def run_targeting(graph: GraphCore, text: str, *, cala: Optional[CalaClient] = None) -> dict[str, Any]:
    cala = cala or CalaClient()
    flt = parse_query(text)
    cala_result = cala.knowledge_query(flt.get("cala_input") or text)
    cala_companies = {row.get("company", "").lower(): row for row in cala_result.get("results", [])}
    targets: list[dict] = []
    matched_companies: list[dict] = []
    for cnode in graph.list_nodes(node_type="company"):
        cname = cnode.label
        in_cala = any(cname.lower() in k or k in cname.lower() for k in cala_companies if k)
        local_ok = _company_matches_local(graph, cnode.id, flt)
        if not (in_cala or local_ok):
            continue
        if not _company_passes_crm(graph, cnode.id, flt.get("crm_employee"), flt.get("crm_min_messages")):
            continue
        people = _people_at_company(graph, cnode.id)
        matched_companies.append({"company_id": cnode.id, "company": cname, "people": len(people)})
        targets.extend(people)
    return {"ok": True, "filters": flt, "cala_mock": cala.is_mock, "cala_source": cala.source,
            "cala_companies": list(cala_companies.keys()), "matched_companies": matched_companies,
            "targets": targets, "count": len(targets)}


def scout_customers(text, *, cala=None, graph=None):
    """Prospect: use only Cala (gpt-4o real knowledge) to find real companies matching the criteria.

    Does not rely on our existing data; if a graph is passed, mark whether each company is already in our network (is_new)."""
    cala = cala or CalaClient()
    flt = parse_query(text)
    result = cala.knowledge_query(flt.get("cala_input") or text)
    rows = result.get("results", [])
    known = set()
    if graph is not None:
        known = {c.label.lower() for c in graph.list_nodes(node_type="company")}
    companies = []
    for r in rows:
        name = r.get("company") or r.get("name") or ""
        if not name:
            continue
        already = any(name.lower() in k or k in name.lower() for k in known if k)
        companies.append({"company": name, "employees": r.get("employees"),
                          "country": r.get("country"), "industry": r.get("industry"),
                          "revenue": r.get("revenue"), "is_new": not already})
    new_companies = [c for c in companies if c["is_new"]]
    return {"ok": True, "mode": "scout", "filters": flt,
            "cala_source": cala.source, "cala_mock": cala.is_mock,
            "companies": companies, "new_companies": new_companies,
            "count": len(companies), "new_count": len(new_companies)}


_WARM_LEAD_HINTS = ("warm lead", "moved", "changed job", "switched", "former contact",
                    "jumped ship", "new employer", "haven't won", "have not won", "no deal yet",
                    "job-hopped", "closed deal", "had a deal", "not yet won", "left the company", "point of contact")


def _is_warm_lead_query(text):
    """True when asking for past-deal contacts who moved to a not-yet-won account."""
    t = (text or "").lower()
    return any(h in t for h in _WARM_LEAD_HINTS)


def find_warm_leads(graph):
    """Warm-lead traversal: won deal -> contact (about_person) -> current employer;
    if we have no won deal at that employer, the contact is a warm lead."""
    deal_company = {}
    for e in graph.query(predicate=S.HAS_DEAL):
        if e.status != "retired":
            deal_company[e.object] = e.subject
    won_company_ids = set()
    won_deals = []
    for deal_id, comp_id in deal_company.items():
        if graph.prop(deal_id, S.DEAL_STAGE) == "won":
            won_company_ids.add(comp_id)
            won_deals.append((deal_id, comp_id))
    leads = []
    seen = set()
    for deal_id, won_company_id in won_deals:
        person_id = graph.prop(deal_id, S.ABOUT_PERSON)
        if not person_id:
            continue
        for e in graph.query(subject=person_id, predicate=S.WORKS_AT):
            if e.status == "retired":
                continue
            current_id = e.object
            if current_id in won_company_ids:
                continue
            key = (person_id, current_id)
            if key in seen:
                continue
            seen.add(key)
            pnode = graph.get_node(person_id)
            won_node = graph.get_node(won_company_id)
            cur_node = graph.get_node(current_id)
            leads.append({
                "person_id": person_id,
                "name": pnode.label if pnode else person_id,
                "title": graph.prop(person_id, S.JOB_TITLE),
                "email": graph.prop(person_id, S.EMAIL),
                "won_company": won_node.label if won_node else won_company_id,
                "won_deal_value": graph.prop(deal_id, S.DEAL_VALUE),
                "current_company": cur_node.label if cur_node else current_id,
                "current_company_id": current_id,
                "current_supplier": graph.prop(current_id, S.CURRENT_SUPPLIER),
                "contract_end": graph.prop(current_id, S.CONTRACT_END_DATE),
            })
    return {"ok": True, "mode": "warm_lead", "leads": leads, "targets": leads, "count": len(leads)}


def filter_network(graph, text):
    """Filter: select contacts only from our own CRM network. Does not call Cala."""
    if _is_warm_lead_query(text):
        return find_warm_leads(graph)
    flt = parse_query(text)
    targets = []
    matched_companies = []
    for cnode in graph.list_nodes(node_type="company"):
        if not _company_matches_local(graph, cnode.id, flt):
            continue
        if not _company_passes_crm(graph, cnode.id, flt.get("crm_employee"), flt.get("crm_min_messages")):
            continue
        people = _people_at_company(graph, cnode.id)
        matched_companies.append({"company_id": cnode.id, "company": cnode.label, "people": len(people)})
        targets.extend(people)
    return {"ok": True, "mode": "filter", "filters": flt,
            "matched_companies": matched_companies,
            "targets": targets, "count": len(targets)}


_SYN={'germany':{'germany','german','deutschland'},'automotive':{'automotive','automobile','car','vehicle','auto'}}
def _syn(v):
    return _SYN.get(str(v).strip().lower(),{str(v).strip().lower()})
def _value_matches(fv,pv):
    if not fv or pv is None:
        return True
    pl=str(pv).lower()
    return any(x in pl or pl in x for x in _syn(fv))


def _company_matches_local(graph: GraphCore, company_id: str, flt: dict) -> bool:
    country = flt.get("country")
    industry = flt.get("industry")
    min_emp = flt.get("min_employees")
    if country and not _value_matches(country, graph.prop(company_id, S.COUNTRY)):
        return False
    if industry and not _value_matches(industry, graph.prop(company_id, S.IN_INDUSTRY)):
        return False
    if min_emp:
        emp = graph.prop(company_id, S.EMPLOYEE_COUNT)
        if emp is not None:
            try:
                if int(emp) < int(min_emp):
                    return False
            except (ValueError, TypeError):
                pass
    return True
