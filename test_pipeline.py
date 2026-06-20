"""Maxx end-to-end smoke test (all mock, no Ollama / real Cala / SMTP needed)."""

from __future__ import annotations

import os

os.environ.setdefault("EMAIL_MOCK", "1")

from graph import GraphCore
from cala import CalaClient
from enrich import scan_and_enrich
from extract import get_sample_card_text
from query import run_targeting
from agent import email_agent, memory
from seed import seed_data


def main() -> None:
    graph = GraphCore()
    seed_data.load_into(graph)
    cala = CalaClient()
    print(f"[Cala] mock={cala.is_mock}  warning={cala.last_warning}")

    print("\n=== (1) Scan card + Cala ripple expansion ===")
    res = scan_and_enrich(
        graph, get_sample_card_text("bosch"),
        cala=cala, activity_cb=lambda e: print(f"   . [{e['status']}] {e['message']}"),
        use_llm=False,
    )
    print(f"   -> person={res['person_id']} company={res['company_id']} "
          f"facts={res['enrichment']['facts_written']}")

    print("\n=== (2) Compose and send cold email (via email tool) ===")
    sent = email_agent.compose_and_send(graph, res["person_id"], use_agent_tool=False)
    print(f"   ok={sent['ok']} subject={sent['draft']['subject']!r} "
          f"mode={sent['send_result'].get('mode')} transport={sent['send_result'].get('transport')}")
    print(f"   thread={sent['thread_id']}")

    print("\n=== (3) Simulate customer reply -> AI replies again (long-term memory) ===")
    reply = email_agent.handle_inbound_reply(
        graph, sent["thread_id"],
        "Hi Tim, we are evaluating new 800V drivetrain suppliers. Send PPM data and lead times.",
        auto_send=True,
    )
    print(f"   reply_subject={reply['reply_subject']!r}")
    print(f"   thread message_count={reply['thread_summary']['message_count']} status={reply['thread_summary']['status']}")

    print("\n=== (4) Natural-language targeting (Cala external intersect CRM private) ===")
    tgt = run_targeting(graph, "people at German automotive manufacturers with more than 3000 employees that Tim emailed 3 times", cala=cala)
    print(f"   parse method: {tgt['filters'].get('_method')}")
    print(f"   filters: country={tgt['filters'].get('country')} industry={tgt['filters'].get('industry')} "
          f"employees>={tgt['filters'].get('min_employees')} | CRM employee={tgt['filters'].get('crm_employee')} "
          f">={tgt['filters'].get('crm_min_messages')} emails")
    print(f"   matched {tgt['count']} people:")
    for t in tgt["targets"]:
        print(f"      - {t['name']} ({t['title']}) <{t['email']}>")

    print("\n[OK] Full pipeline passed.")


if __name__ == "__main__":
    main()
