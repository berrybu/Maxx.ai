"""Use real Ollama (a live model) to generate a cold email, reusing the project's RAG and graph context.
This machine has no pip to install langchain, so we call the Ollama HTTP API directly with httpx to prove the LLM path works."""
import os, httpx
os.environ.setdefault("EMAIL_MOCK", "1")
from graph import GraphCore
from cala import CalaClient
from enrich import scan_and_enrich
from extract import get_sample_card_text
from agent import rag
from agent.email_agent import _gather_context, _COMPOSE_SYSTEM
from graph import schema as S

MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss-20b")

g = GraphCore()
cala = CalaClient()
res = scan_and_enrich(g, get_sample_card_text("bosch"), cala=cala, use_llm=False)
ctx = _gather_context(g, res["person_id"])
product_ctx = rag.retrieve(f"{ctx.get('company_name')} {ctx.get('title')}", k=3)
user = (f"### Product doc (excerpt)\n{product_ctx}\n\n### Prospect profile\n"
        f"Name:{ctx['name']} Title:{ctx['title']} Company:{ctx['company_name']}\n"
        f"Company facts:{ctx['company_facts']}\n\nPlease write this cold email, with the subject on the first line as 'Subject: ...'.")
print(f"[model] {MODEL}  recipient: {ctx['name']} <{ctx['email']}> @ {ctx['company_name']}")
print("[calling Ollama to generate...]\n")
r = httpx.post("http://localhost:11434/api/chat", timeout=300, json={
    "model": MODEL, "stream": False,
    "messages": [{"role": "system", "content": _COMPOSE_SYSTEM},
                 {"role": "user", "content": user}],
    "options": {"temperature": 0.3}})
r.raise_for_status()
print(r.json()["message"]["content"])
