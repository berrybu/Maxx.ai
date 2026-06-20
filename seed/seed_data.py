"""Demo seed data -- the "warm lead" use case driven by deal + employment history.

Storyline that the graph traversal can answer:
  We WON a PCB deal at Hella, where our contact was Andrea Richter (closed by Tim).
  Andrea has since moved on -- she now works at BMW, an account where we have NO won
  deal yet. So:  won deal -> about_person -> their CURRENT employer (no deal) = warm lead.

It also exercises all four newly added CRM extensions:
  1. Trade / deal history          -> record_deal (Continental + Hella, both won)
  2. Email history by employee     -> employee nodes + handled_by / account_owner
  3. Competitor / supplier intel   -> BMW buys_from Wuerth Elektronik + contract end
  4. Interaction / activity log    -> a trade-show meeting with Klaus

Continental + Klaus + a thread where Tim sent 3 emails is kept intact so the original
"German automotive >3000 employees that Tim emailed 3 times" filter still hits.
"""

from __future__ import annotations

import re

from graph import Edge, GraphCore, Node
from graph import schema as S
from agent import memory


def load_into(graph: GraphCore) -> None:
    # ---- Products we sell ----
    pcb16 = "n_product_pcb16layer"
    pcb12 = "n_product_pcb12layer"
    graph.upsert_node(Node(id=pcb16, type="product", label="PCB-16layer"))
    graph.upsert_node(Node(id=pcb12, type="product", label="PCB-12layer"))

    # ================================================================
    # US: our own company (a PCB seller) + me, the sales person
    # ================================================================
    ME = "Tianhao Gu"

    us = "n_company_maxxcomponents"
    graph.upsert_node(Node(id=us, type="us_company", label="Maxx Components"))
    for pred, val, conf in [
        (S.COUNTRY, "Germany", 1.0),
        (S.IN_INDUSTRY, "PCB manufacturing", 1.0),
        (S.WEBSITE, "maxx-components.com", 1.0),
        ("recent_news", "Maxx Components -- high-reliability PCB seller: HDI, heavy copper and RF boards for automotive.", 1.0),
    ]:
        graph.add_confirmed(Edge(subject=us, predicate=pred, object=val,
                                 source="crm", extractor="human", confidence=conf))
    # we are the seller of these products
    graph.add_confirmed(Edge(subject=us, predicate="sells", object=pcb16,
                             source="crm", extractor="human", confidence=1.0))
    graph.add_confirmed(Edge(subject=us, predicate="sells", object=pcb12,
                             source="crm", extractor="human", confidence=1.0))

    # me -- the sales person, an employee of our own company
    me_id = memory.get_or_create_employee(graph, ME)
    graph.add_confirmed(Edge(subject=me_id, predicate=S.JOB_TITLE, object="Senior B2B Sales Manager",
                             source="crm", extractor="human", confidence=1.0))
    graph.add_confirmed(Edge(subject=me_id, predicate=S.EMAIL, object="tianhao.gu@maxx-components.com",
                             source="crm", extractor="human", confidence=1.0))
    graph.add_confirmed(Edge(subject=me_id, predicate="employed_by", object=us,
                             source="crm", extractor="human", confidence=1.0))

    # ================================================================
    # Company A: Continental -- an existing won account (keeps old demo working)
    # ================================================================
    conti = "n_company_continentalag"
    graph.upsert_node(Node(id=conti, type="company", label="Continental AG"))
    for pred, val, conf in [
        (S.COUNTRY, "Germany", 0.95),
        (S.EMPLOYEE_COUNT, 200000, 0.9),
        (S.IN_INDUSTRY, "automotive parts", 0.9),
        (S.REVENUE, "€40B", 0.8),
        ("recent_news", "Continental is looking for sensor suppliers for its next-generation ADAS systems.", 0.8),
    ]:
        graph.add_confirmed(Edge(subject=conti, predicate=pred, object=val,
                                 source="cala", extractor="Cala", confidence=conf))

    # Contact: Klaus Weber (still at Continental)
    klaus = "n_person_klausweber"
    graph.upsert_node(Node(id=klaus, type="person", label="Klaus Weber"))
    memory.record_employment(graph, klaus, conti, current=True, source="business_card", confidence=1.0)
    graph.add_confirmed(Edge(subject=klaus, predicate=S.JOB_TITLE, object="VP Procurement",
                             source="business_card", extractor="OCR", confidence=0.95))
    graph.add_confirmed(Edge(subject=klaus, predicate=S.EMAIL, object="klaus.weber@continental.com",
                             source="business_card", extractor="OCR", confidence=0.95))

    # Tim owns the Continental account
    memory.set_account_owner(graph, conti, ME)

    # Trade history: a won PCB-16layer order at Continental, closed by Tim
    memory.record_deal(
        graph, conti, stage="won", product_id=pcb16, value="€420,000",
        quantity=12000, order_date="2024-03-01", delivery_date="2024-09-15",
        about_person_id=klaus, employee=ME,
    )

    # Long-term memory: Tim has already sent 3 emails to Continental
    thread = memory.get_or_create_thread(graph, conti, about_person_id=klaus, employee=ME)
    memory.record_message(graph, thread, direction="outbound",
                          subject="Intro: Maxx high-reliability PCBs", body="Hi Klaus, ...", employee=ME)
    memory.record_message(graph, thread, direction="outbound",
                          subject="Following up", body="Hi Klaus, circling back ...", employee=ME)
    memory.record_message(graph, thread, direction="outbound",
                          subject="ADAS sensor boards", body="Hi Klaus, re your ADAS program ...", employee=ME)

    # Activity log: met Klaus at a trade show, positive, follow-up scheduled
    memory.record_activity(
        graph, klaus, activity_type="meeting", date="2025-11-12",
        summary="Met Klaus at productronica 2025; discussed 16-layer HDI roadmap.",
        outcome="positive", next_followup="2026-07-01", employee=ME,
    )

    # ================================================================
    # Company B: Hella -- a PAST won account; our contact there has since left
    # ================================================================
    hella = "n_company_hella"
    graph.upsert_node(Node(id=hella, type="company", label="Hella"))
    for pred, val, conf in [
        (S.COUNTRY, "Germany", 0.95),
        (S.EMPLOYEE_COUNT, 36000, 0.9),
        (S.IN_INDUSTRY, "automotive parts", 0.9),
    ]:
        graph.add_confirmed(Edge(subject=hella, predicate=pred, object=val,
                                 source="cala", extractor="Cala", confidence=conf))
    memory.set_account_owner(graph, hella, ME)

    # Andrea Richter: former Hella (where we won), now at BMW
    andrea = "n_person_andrearichter"
    graph.upsert_node(Node(id=andrea, type="person", label="Andrea Richter"))
    memory.record_employment(graph, andrea, hella, current=False, source="crm", confidence=0.9)  # former
    graph.add_confirmed(Edge(subject=andrea, predicate=S.JOB_TITLE, object="Head of Hardware Procurement",
                             source="cala", extractor="Cala", confidence=0.85))

    # Trade history: a won PCB-12layer order at Hella, closed by Tim, contact = Andrea
    memory.record_deal(
        graph, hella, stage="won", product_id=pcb12, value="€180,000",
        quantity=5000, order_date="2023-06-15", delivery_date="2023-12-01",
        about_person_id=andrea, employee=ME,
    )

    # ================================================================
    # Company C: BMW -- the WARM LEAD (no won deal yet, but Andrea now works here)
    # ================================================================
    bmw = "n_company_bmwag"
    graph.upsert_node(Node(id=bmw, type="company", label="BMW AG"))
    for pred, val, conf in [
        (S.COUNTRY, "Germany", 0.95),
        (S.EMPLOYEE_COUNT, 150000, 0.9),
        (S.IN_INDUSTRY, "automotive parts", 0.9),
        (S.REVENUE, "€142B", 0.8),
        ("recent_news", "BMW Neue Klasse ramp-up is increasing demand for high-layer-count control boards.", 0.8),
    ]:
        graph.add_confirmed(Edge(subject=bmw, predicate=pred, object=val,
                                 source="cala", extractor="Cala", confidence=conf))

    # Andrea's CURRENT employer is BMW -> this is what makes BMW a warm lead
    memory.record_employment(graph, andrea, bmw, current=True, source="cala", confidence=0.8)
    graph.add_confirmed(Edge(subject=andrea, predicate=S.EMAIL, object="andrea.richter@bmw.de",
                             source="cala", extractor="Cala", confidence=0.7))

    # Competitor / incumbent-supplier intel: BMW currently buys from a rival, contract ending soon
    memory.record_supplier_intel(
        graph, bmw, supplier_name="Wuerth Elektronik",
        contract_end_date="2026-09-30", share_of_wallet="70%",
        source="cala", confidence=0.7,
    )


    # ================================================================
    # Sales pipeline -- extra deals across stages (powers the Attio-style grid)
    # ================================================================
    def _add_pipeline_deal(company, country, employees, industry, contact, title,
                           email, stage, value, strength, next_step):
        cid = "n_company_" + re.sub(r"\W", "", company.lower())
        graph.upsert_node(Node(id=cid, type="company", label=company))
        for pred, val, conf in [
            (S.COUNTRY, country, 0.95),
            (S.EMPLOYEE_COUNT, employees, 0.9),
            (S.IN_INDUSTRY, industry, 0.9),
        ]:
            graph.add_confirmed(Edge(subject=cid, predicate=pred, object=val,
                                     source="crm", extractor="human", confidence=conf))
        pid = "n_person_" + re.sub(r"\W", "", contact.lower())
        graph.upsert_node(Node(id=pid, type="person", label=contact))
        memory.record_employment(graph, pid, cid, current=True, source="crm", confidence=0.95)
        graph.add_confirmed(Edge(subject=pid, predicate=S.JOB_TITLE, object=title,
                                 source="crm", extractor="human", confidence=0.9))
        graph.add_confirmed(Edge(subject=pid, predicate=S.EMAIL, object=email,
                                 source="crm", extractor="human", confidence=0.9))
        memory.set_account_owner(graph, cid, ME)
        did = memory.record_deal(graph, cid, stage=stage, value=value,
                                 about_person_id=pid, employee=ME)
        graph.add_confirmed(Edge(subject=did, predicate=S.CONNECTION_STRENGTH, object=strength,
                                 source="crm", extractor="human", confidence=1.0))
        graph.add_confirmed(Edge(subject=did, predicate=S.NEXT_STEP, object=next_step,
                                 source="crm", extractor="human", confidence=1.0))
        return did

    _add_pipeline_deal("Aptiv", "Ireland", 200000, "automotive parts",
                       "Sofia Marino", "Director of Hardware Engineering",
                       "sofia.marino@aptiv.com", "won", "EUR 520,000",
                       "very_strong", "Reorder review - next week")
    _add_pipeline_deal("ZF Friedrichshafen", "Germany", 165000, "automotive parts",
                       "Markus Holt", "Senior Buyer Electronics",
                       "markus.holt@zf.com", "qualified", "EUR 280,000",
                       "strong", "Technical call - Tomorrow")
    _add_pipeline_deal("Valeo", "France", 110000, "automotive parts",
                       "Camille Laurent", "Procurement Lead PCBA",
                       "camille.laurent@valeo.com", "quoted", "EUR 150,000",
                       "good", "Quote follow-up - Friday")
    _add_pipeline_deal("Magna International", "Canada", 170000, "automotive parts",
                       "Daniel Cho", "Commodity Manager",
                       "daniel.cho@magna.com", "lead", "EUR 95,000",
                       "weak", "Intro meeting - In 3 days")
    _add_pipeline_deal("Marelli", "Italy", 54000, "automotive parts",
                       "Giulia Rossi", "Head of Sourcing",
                       "giulia.rossi@marelli.com", "qualified", "EUR 210,000",
                       "strong", "Send capability deck - Today")
    _add_pipeline_deal("Forvia", "France", 150000, "automotive parts",
                       "Pierre Dubois", "PCB Category Buyer",
                       "pierre.dubois@forvia.com", "quoted", "EUR 175,000",
                       "good", "Pricing review - Thursday")
    _add_pipeline_deal("Denso", "Japan", 168000, "automotive parts",
                       "Kenji Sato", "Supplier Quality Engineer",
                       "kenji.sato@denso.com", "lost", "EUR 60,000",
                       "very_weak", "Re-engage in Q4")
    _add_pipeline_deal("Aptiv Poland", "Poland", 12000, "automotive parts",
                       "Anna Kowalski", "Plant Procurement",
                       "anna.kowalski@aptiv.com", "lead", "EUR 70,000",
                       "weak", "Site visit - Next month")

    # enrich the two original won deals so every grid row has strength + next step
    for _cid in (conti, hella):
        for _e in graph.query(predicate=S.HAS_DEAL, subject=_cid):
            _did = _e.object
            graph.add_confirmed(Edge(subject=_did, predicate=S.CONNECTION_STRENGTH,
                                     object="very_strong", source="crm", extractor="human", confidence=1.0))
            graph.add_confirmed(Edge(subject=_did, predicate=S.NEXT_STEP,
                                     object="Renewal review - Next month", source="crm", extractor="human", confidence=1.0))
