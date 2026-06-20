"""Long-term memory -- write email exchanges and conversation records into the CRM graph."""

from __future__ import annotations

import time
from typing import Any, Optional

from graph import Edge, GraphCore, Node, new_id
from graph import schema as S


def get_or_create_thread(graph: GraphCore, company_id: str, *, about_person_id: Optional[str] = None, employee: str = "Tim") -> str:
    existing = graph.query(subject=company_id, predicate=S.HAS_EMAIL_THREAD)
    for e in existing:
        if e.status != "retired":
            return e.object
    company = graph.get_node(company_id)
    label = f"Email thread · {company.label if company else company_id}"
    thread_id = new_id("n_thread")
    graph.upsert_node(Node(id=thread_id, type="email_thread", label=label))
    graph.add_confirmed(Edge(subject=company_id, predicate=S.HAS_EMAIL_THREAD, object=thread_id,
                             source="crm", extractor="system", confidence=1.0))
    if about_person_id:
        graph.add_confirmed(Edge(subject=thread_id, predicate=S.ABOUT_PERSON, object=about_person_id,
                                 source="crm", extractor="system", confidence=1.0))
    graph.add_confirmed(Edge(subject=thread_id, predicate=S.SENT_BY_EMPLOYEE, object=employee,
                             source="crm", extractor="system", confidence=1.0))
    graph.add_confirmed(Edge(subject=thread_id, predicate=S.THREAD_STATUS, object="cold",
                             source="crm", extractor="system", confidence=1.0))
    graph.add_confirmed(Edge(subject=thread_id, predicate=S.MESSAGE_COUNT, object=0,
                             source="crm", extractor="system", confidence=1.0))
    return thread_id


def record_message(graph: GraphCore, thread_id: str, *, direction: str, subject: str, body: str, employee: str = "Tim") -> dict[str, Any]:
    msg_id = new_id("msg")
    payload = {"id": msg_id, "direction": direction, "subject": subject, "body": body, "t": time.time(), "employee": employee}
    graph.add_confirmed(Edge(subject=thread_id, predicate="message", object=payload,
                             source="crm", extractor="system", confidence=1.0))
    # Email attribution: link this thread to the rep who handled it (multi-rep aware).
    if employee:
        link_thread_employee(graph, thread_id, employee)
    count = int(graph.prop(thread_id, S.MESSAGE_COUNT, default=0) or 0) + 1
    _set_thread_field(graph, thread_id, S.MESSAGE_COUNT, count)
    _set_thread_field(graph, thread_id, S.LAST_CONTACT, time.strftime("%Y-%m-%d"))
    new_status = "replied" if direction == "inbound" else "sent"
    _set_thread_field(graph, thread_id, S.THREAD_STATUS, new_status)
    return {"message_id": msg_id, "message_count": count, "status": new_status}


def get_history(graph: GraphCore, thread_id: str) -> list[dict]:
    msgs = [e.object for e in graph.query(subject=thread_id, predicate="message") if isinstance(e.object, dict)]
    msgs.sort(key=lambda m: m.get("t", 0))
    return msgs


def thread_summary(graph: GraphCore, thread_id: str) -> dict[str, Any]:
    return {"thread_id": thread_id, "status": graph.prop(thread_id, S.THREAD_STATUS, default="cold"),
            "message_count": graph.prop(thread_id, S.MESSAGE_COUNT, default=0),
            "sent_by_employee": graph.prop(thread_id, S.SENT_BY_EMPLOYEE, default=None),
            "last_contact": graph.prop(thread_id, S.LAST_CONTACT, default=None),
            "messages": get_history(graph, thread_id)}


def _set_thread_field(graph: GraphCore, thread_id: str, predicate: str, value: Any) -> None:
    for e in graph.query(subject=thread_id, predicate=predicate):
        if e.status != "retired":
            graph.retire(e.id)
    graph.add_confirmed(Edge(subject=thread_id, predicate=predicate, object=value,
                             source="crm", extractor="system", confidence=1.0))


# ======================================================================
# Sales reps (our own employees) + email attribution
# ======================================================================
def get_or_create_employee(graph: GraphCore, name: str) -> str:
    """Find (or create) one of our own sales reps as an `employee` node, returning its id."""
    node = graph.find_node(node_type="employee", label=name)
    if node:
        return node.id
    emp_id = new_id("n_emp")
    graph.upsert_node(Node(id=emp_id, type="employee", label=name))
    graph.add_confirmed(
        Edge(subject=emp_id, predicate=S.EMPLOYEE_NAME, object=name,
             source="crm", extractor="system", confidence=1.0)
    )
    return emp_id


def link_thread_employee(graph: GraphCore, thread_id: str, employee: str) -> str:
    """Attribute an email thread to the rep who handled it (idempotent, multi-rep aware)."""
    emp_id = get_or_create_employee(graph, employee)
    for e in graph.query(subject=thread_id, predicate=S.HANDLED_BY):
        if e.object == emp_id and e.status != "retired":
            return emp_id
    graph.add_confirmed(
        Edge(subject=thread_id, predicate=S.HANDLED_BY, object=emp_id,
             source="crm", extractor="system", confidence=1.0)
    )
    return emp_id


def set_account_owner(graph: GraphCore, company_id: str, employee: str) -> str:
    """Assign a company's account owner (our rep)."""
    emp_id = get_or_create_employee(graph, employee)
    for e in graph.query(subject=company_id, predicate=S.ACCOUNT_OWNER):
        if e.status != "retired":
            graph.retire(e.id)
    graph.add_confirmed(
        Edge(subject=company_id, predicate=S.ACCOUNT_OWNER, object=emp_id,
             source="crm", extractor="system", confidence=1.0)
    )
    return emp_id


# ======================================================================
# Employment history (current vs former employer) -- powers warm-lead traversal
# ======================================================================
def record_employment(
    graph: GraphCore,
    person_id: str,
    company_id: str,
    *,
    current: bool = True,
    source: str = "business_card",
    confidence: float = 0.9,
) -> None:
    """Record where a contact works. current=True -> works_at, False -> worked_at (former)."""
    pred = S.WORKS_AT if current else S.WORKED_AT
    graph.add_confirmed(
        Edge(subject=person_id, predicate=pred, object=company_id,
             source=source, extractor="human", confidence=confidence)
    )


# ======================================================================
# Trade / deal history (highest-value CRM extension)
# ======================================================================
def record_deal(
    graph: GraphCore,
    company_id: str,
    *,
    stage: str = "won",
    product_id: Optional[str] = None,
    value: Optional[str] = None,
    quoted_price: Optional[str] = None,
    quantity: Optional[Any] = None,
    order_date: Optional[str] = None,
    delivery_date: Optional[str] = None,
    about_person_id: Optional[str] = None,
    employee: Optional[str] = None,
    source: str = "crm",
    confidence: float = 1.0,
) -> str:
    """Write a deal/order (won/lost/quoted...) into the graph and return its node id."""
    if stage not in S.DEAL_STAGES:
        raise ValueError(f"deal stage must be one of {S.DEAL_STAGES}, got {stage!r}")
    company = graph.get_node(company_id)
    deal_id = new_id("n_deal")
    label = f"Deal - {company.label if company else company_id} ({stage})"
    graph.upsert_node(Node(id=deal_id, type="deal", label=label))
    graph.add_confirmed(
        Edge(subject=company_id, predicate=S.HAS_DEAL, object=deal_id,
             source=source, extractor="system", confidence=confidence)
    )

    def _set(pred: str, val: Any) -> None:
        graph.add_confirmed(
            Edge(subject=deal_id, predicate=pred, object=val,
                 source=source, extractor="system", confidence=confidence)
        )

    _set(S.DEAL_STAGE, stage)
    if product_id is not None:
        _set(S.DEAL_PRODUCT, product_id)
    if value is not None:
        _set(S.DEAL_VALUE, value)
    if quoted_price is not None:
        _set(S.QUOTED_PRICE, quoted_price)
    if quantity is not None:
        _set(S.QUANTITY, quantity)
    if order_date is not None:
        _set(S.ORDER_DATE, order_date)
    if delivery_date is not None:
        _set(S.DELIVERY_DATE, delivery_date)
    if about_person_id is not None:
        _set(S.ABOUT_PERSON, about_person_id)
    if employee is not None:
        _set(S.WON_BY, get_or_create_employee(graph, employee))
    return deal_id


# ======================================================================
# Competitor / incumbent-supplier intelligence (displacement selling)
# ======================================================================
def record_supplier_intel(
    graph: GraphCore,
    company_id: str,
    *,
    supplier_name: Optional[str] = None,
    contract_end_date: Optional[str] = None,
    share_of_wallet: Optional[str] = None,
    source: str = "cala",
    confidence: float = 0.7,
) -> Optional[str]:
    """Record who a prospect currently buys from + commercial timing. Returns supplier node id."""
    supplier_id = None
    if supplier_name:
        sup = graph.find_node(node_type="company", label=supplier_name)
        if sup is None:
            supplier_id = new_id("n_company")
            graph.upsert_node(Node(id=supplier_id, type="company", label=supplier_name))
        else:
            supplier_id = sup.id
        graph.add_confirmed(
            Edge(subject=company_id, predicate=S.BUYS_FROM, object=supplier_id,
                 source=source, extractor="Cala", confidence=confidence)
        )
        graph.add_confirmed(
            Edge(subject=company_id, predicate=S.CURRENT_SUPPLIER, object=supplier_name,
                 source=source, extractor="Cala", confidence=confidence)
        )
    if contract_end_date is not None:
        graph.add_confirmed(
            Edge(subject=company_id, predicate=S.CONTRACT_END_DATE, object=contract_end_date,
                 source=source, extractor="Cala", confidence=confidence)
        )
    if share_of_wallet is not None:
        graph.add_confirmed(
            Edge(subject=company_id, predicate=S.SHARE_OF_WALLET, object=share_of_wallet,
                 source=source, extractor="Cala", confidence=confidence)
        )
    return supplier_id


# ======================================================================
# Interaction / activity log (calls, meetings, events -- beyond email)
# ======================================================================
def record_activity(
    graph: GraphCore,
    subject_id: str,
    *,
    activity_type: str,
    date: Optional[str] = None,
    summary: Optional[str] = None,
    outcome: Optional[str] = None,
    next_followup: Optional[str] = None,
    employee: Optional[str] = None,
    source: str = "crm",
    confidence: float = 1.0,
) -> str:
    """Log a non-email touch (call/meeting/event/...) against a company or person."""
    if activity_type not in S.ACTIVITY_TYPES:
        raise ValueError(f"activity_type must be one of {S.ACTIVITY_TYPES}, got {activity_type!r}")
    act_id = new_id("n_act")
    label = f"{activity_type}" + (f" - {date}" if date else "")
    graph.upsert_node(Node(id=act_id, type="activity", label=label))
    graph.add_confirmed(
        Edge(subject=subject_id, predicate=S.HAS_ACTIVITY, object=act_id,
             source=source, extractor="system", confidence=confidence)
    )

    def _set(pred: str, val: Any) -> None:
        graph.add_confirmed(
            Edge(subject=act_id, predicate=pred, object=val,
                 source=source, extractor="system", confidence=confidence)
        )

    _set(S.ACTIVITY_TYPE, activity_type)
    if date is not None:
        _set(S.ACTIVITY_DATE, date)
    if summary is not None:
        _set(S.ACTIVITY_SUMMARY, summary)
    if outcome is not None:
        _set(S.ACTIVITY_OUTCOME, outcome)
    if next_followup is not None:
        _set(S.NEXT_FOLLOWUP, next_followup)
    if employee is not None:
        _set(S.WON_BY, get_or_create_employee(graph, employee))
    return act_id
