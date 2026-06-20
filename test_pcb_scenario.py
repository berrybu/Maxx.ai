"""PCB manufacturer sales scenario -- end-to-end test."""
import os

os.environ.setdefault("LLM_PROVIDER", "bricksllm")
os.environ.setdefault("EMAIL_MOCK", "1")
os.environ["PRODUCT_DOC"] = "docs/pcb_product_doc.md"
os.environ["SELLER_NAME"] = "Tim"
os.environ["SELLER_COMPANY"] = "EuroCircuit PCB"
os.environ["SELLER_DESC"] = "German high-reliability printed circuit board (PCB) manufacturer"

from cala import CalaClient
from graph import GraphCore
from graph import schema as S
from enrich import scan_and_enrich
from query import run_targeting
import agent.email_agent as ea

CARD = (
    "Continental AG\n"
    "Klaus Weber — Head of Hardware Procurement\n"
    "klaus.weber@continental.com\n"
    "+49 511 938 02\n"
    "Hannover, Germany"
)


def banner(t):
    print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)


def main():
    use_llm = os.environ.get("LLM_PROVIDER") == "bricksllm" and bool(os.environ.get("BRICKSLLM_API_KEY"))
    print(f"LLM mode: {'BricksLLM gpt-4o' if use_llm else 'mock/heuristic'}")
    g = GraphCore(store_path="/tmp/maxx_pcb.json")
    cala = CalaClient()

    banner("(1) Scan card -> extract -> write to CRM knowledge graph -> (2) Cala ripple expansion")
    events = []
    res = scan_and_enrich(g, CARD, cala=cala, activity_cb=events.append, use_llm=use_llm)
    for e in events:
        print(f"  . [{e['status']}] {e['message']}")
    card = res["card"]
    print(f"\nextract({card.get('_method')}): {card.get('full_name')} / {card.get('job_title')} @ {card.get('company')}")
    person_id, company_id = res["person_id"], res["company_id"]
    facts = {p: g.prop(company_id, p) for p in [S.EMPLOYEE_COUNT, S.COUNTRY, S.IN_INDUSTRY, S.REVENUE]}
    print("Cala wrote back company facts:", facts)
    print("latest news (email hook):", g.prop(company_id, "recent_news"))

    banner("(3) Cold email: Agent reads the PCB technical doc (RAG) + graph profile -> sends via MCP")
    out = ea.compose_and_send(g, person_id, use_agent_tool=use_llm)
    d = out["draft"]
    print("Subject:", d.get("subject"))
    print("Body:\n", d.get("body"))
    print("\nsend:", out["send_result"].get("ok"), "| tool calls:", [t["name"] for t in out["tool_calls"]])

    banner("(4) Buyer replies with technical questions -> AI answers using RAG over the PCB doc")
    buyer = ("Thanks for your email. Our next-gen ADAS domain controller needs automotive-grade HDI boards. A few questions:\n"
             "1) How many layers can you do at most? What is the minimum trace width/spacing?\n"
             "2) What impedance tolerance can you control to? Do you provide an impedance test report with the shipment?\n"
             "3) What is the prototype lead time? Are you IATF 16949 certified?")
    print("Buyer message:\n", buyer)
    rep = ea.handle_inbound_reply(g, out["thread_id"], buyer, auto_send=use_llm)
    print("\nAI reply subject:", rep["reply_subject"])
    print("AI reply body:\n", rep["reply_body"])
    print("\nreply sent:", (rep["send_result"] or {}).get("ok"))
    print("(5) thread long-term memory message count:", len(rep["thread_summary"]["messages"]))

    banner("(6) Natural-language targeting: people at German automotive companies with >3000 employees that Tim emailed 3 times")
    q = "people at German automotive companies with more than 3000 employees that Tim emailed 3 times"
    tg = run_targeting(g, q, cala=cala)
    print("parsed filters:", {k: tg["filters"].get(k) for k in
                    ["country", "industry", "min_employees", "crm_employee", "crm_min_messages"]})
    print("matched companies:", tg["matched_companies"])
    print("target contacts:")
    for t in tg["targets"]:
        print(f"  -> {t['name']} / {t['title']} <{t['email']}>")
    assert tg["count"] >= 1, "targeting should match at least 1 contact"
    print("\nPCB scenario end-to-end passed.")


if __name__ == "__main__":
    main()
