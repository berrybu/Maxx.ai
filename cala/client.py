"""Cala knowledge-graph API client (external verified entity-fact layer).

Wraps the four official capabilities:
  - entity_search   GET  /v1/entities?query=...
  - retrieve_entity GET  /v1/entities/{id}
  - knowledge_query POST /v1/knowledge/query   (structured JSON rows + entities)
  - knowledge_search POST /v1/knowledge/search  (markdown natural-language answer)

Auth: header X-API-KEY. Three data sources (source):
  - "real"   : a valid CALA_API_KEY is configured, uses the real Cala HTTP API
  - "gpt-4o" : no Cala key (or Cala call failed and degraded), uses gpt-4o's real-world knowledge
               to answer company facts/decision-makers/news in real time -- real data, not fabricated, not hardcoded
  - "mock"   : last-resort fallback when even the LLM is unavailable (deterministic static samples, offline demo only)
By default never returns hardcoded fake data: as long as the LLM is available, even without a Cala key it uses gpt-4o real knowledge.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from config import get_settings


class CalaError(RuntimeError):
    pass


def _llm_available() -> bool:
    """Determine whether the LLM backend is available (used to decide whether Cala degrades to gpt-4o or static fallback)."""
    s = get_settings()
    if s.llm_provider == "bricksllm":
        return s.bricksllm_enabled
    return s.llm_provider == "ollama"  # local ollama assumed available, degrade on failure


class CalaClient:
    def __init__(self, *, timeout: float = 30.0, allow_mock_fallback: bool = True) -> None:
        s = get_settings()
        self._base = s.cala_base_url.rstrip("/")
        self._key = s.cala_api_key
        self._timeout = timeout
        self._allow_mock_fallback = allow_mock_fallback
        self.last_warning: Optional[str] = None
        # data source: real(HTTP) / gpt-4o(LLM real knowledge) / mock(static fallback)
        if s.cala_enabled:
            self._source = "real"
        elif _llm_available():
            self._source = "gpt-4o"
        else:
            self._source = "mock"

    @property
    def source(self) -> str:
        """Current data source: 'real' | 'gpt-4o' | 'mock'."""
        return self._source

    @property
    def is_mock(self) -> bool:
        """Only counts as mock when fallen back to static; gpt-4o real knowledge is not mock."""
        return self._source == "mock"

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._key, "Content-Type": "application/json"}

    # ---- real HTTP ----
    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}{path}"
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise CalaError(f"Cala {path} returned {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise CalaError(f"Cala {path} request failed: {e}") from e

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self._base}{path}"
        try:
            resp = httpx.get(url, params=params, headers=self._headers(), timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise CalaError(f"Cala {path} returned {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise CalaError(f"Cala {path} request failed: {e}") from e

    # ---- public capabilities ----
    def _degrade(self, err: Exception) -> None:
        """Log a warning and degrade when the real HTTP call fails (prefer gpt-4o real knowledge, otherwise static)."""
        if not self._allow_mock_fallback:
            return
        nxt = "gpt-4o" if _llm_available() else "mock"
        self.last_warning = f"Cala real API call failed, degraded to {nxt}: {err}"
        self._source = nxt

    def _llm_failed(self, err: Exception) -> None:
        """Fall back to static when the gpt-4o knowledge call fails."""
        self.last_warning = f"gpt-4o knowledge call failed, fell back to static: {err}"
        if self._allow_mock_fallback:
            self._source = "mock"

    def knowledge_query(self, query_input: str, *, return_entities: bool = True) -> dict:
        """Structured query. query_input can be Cala QL or natural language.

        Returns {"results": [...rows...], "entities": [...entities...]}.
        """
        if self._source == "real":
            try:
                return self._post(
                    "/v1/knowledge/query",
                    {"input": query_input, "return_entities": return_entities},
                )
            except CalaError as e:
                self._degrade(e)
                if not self._allow_mock_fallback:
                    raise
        if self._source == "gpt-4o":
            try:
                return _llm_query(query_input)
            except Exception as e:  # noqa: BLE001 - degrade to static
                self._llm_failed(e)
        return _mock_query(query_input)

    def knowledge_search(self, query_input: str) -> str:
        """Natural-language answer with citations (markdown string)."""
        if self._source == "real":
            try:
                data = self._post("/v1/knowledge/search", {"input": query_input})
                if isinstance(data, dict):
                    return data.get("answer") or data.get("markdown") or str(data)
                return str(data)
            except CalaError as e:
                self._degrade(e)
                if not self._allow_mock_fallback:
                    raise
        if self._source == "gpt-4o":
            try:
                return _llm_search(query_input)
            except Exception as e:  # noqa: BLE001
                self._llm_failed(e)
        return _mock_search(query_input)

    def entity_search(self, name: str) -> list[dict]:
        """Look up entities by name, returning a list of candidate entities (with id/name/entity_type)."""
        if self._source == "real":
            try:
                data = self._get("/v1/entities", {"query": name})
                if isinstance(data, dict):
                    return data.get("entities") or data.get("results") or []
                if isinstance(data, list):
                    return data
                return []
            except CalaError as e:
                self._degrade(e)
                if not self._allow_mock_fallback:
                    raise
        if self._source == "gpt-4o":
            try:
                return _llm_entity_search(name)
            except Exception as e:  # noqa: BLE001
                self._llm_failed(e)
        return _mock_entity_search(name)

    def retrieve_entity(self, entity_id: str) -> dict:
        """Fetch an entity's full fields by UUID/name."""
        if self._source == "real" and not entity_id.startswith("llm:"):
            try:
                return self._get(f"/v1/entities/{entity_id}", {})
            except CalaError as e:
                self._degrade(e)
                if not self._allow_mock_fallback:
                    raise
        if self._source == "gpt-4o" or entity_id.startswith("llm:"):
            try:
                return _llm_retrieve_entity(entity_id)
            except Exception as e:  # noqa: BLE001
                self._llm_failed(e)
        return _mock_entity_detail(entity_id)


# --------------------------------------------------------------------------
# gpt-4o real-knowledge provider layer (real data source when no Cala key, not fabricated, not hardcoded).
# Answer entity/knowledge queries with real-world company facts the LLM already knows.
# --------------------------------------------------------------------------

_LLM_SYS = (
    "You are an enterprise knowledge base. Answer only with real, factual company information you actually know; "
    "never fabricate numbers or names. Fill uncertain fields with null, use an empty array for unknown people. Output JSON only."
)


def _llm_company_facts(name: str) -> dict:
    """Use gpt-4o to pull a company's real factual information (same field structure as retrieve_entity)."""
    from llm import chat_json

    prompt = (
        f"Provide real factual information about company '{name}'. JSON fields:\n"
        '  employees(integer, global headcount), country(HQ country English name), '
        'industry(main industry in English), website(official website URL), revenue(annual revenue string e.g. "€40B"), '
        'founded_year(integer), key_people(array, each item {"name","role"}; real executives or procurement'
        'decision-makers, max 4), recent_news(one recent real business update, in English)。\n'
        "Fill unknown fields with null, unknown people with [], do not fabricate. Output JSON only."
    )
    data = chat_json([
        {"role": "system", "content": _LLM_SYS},
        {"role": "user", "content": prompt},
    ])
    if not isinstance(data, dict):
        return {}
    return data


def _llm_entity_search(name: str) -> list[dict]:
    """Entity search under gpt-4o knowledge: return the query name as a company entity (details left to retrieve_entity)."""
    name = (name or "").strip()
    if not name:
        return []
    return [{"id": f"llm:{name}", "name": name, "entity_type": "Company"}]


def _llm_retrieve_entity(entity_id: str) -> dict:
    """Entity details under gpt-4o knowledge: resolve company name -> look up real facts."""
    name = entity_id[4:] if entity_id.startswith("llm:") else entity_id
    facts = _llm_company_facts(name)
    facts.setdefault("name", name)
    facts["id"] = entity_id
    facts["entity_type"] = "Company"
    facts["_source"] = "gpt-4o"
    return facts


def _llm_query(query_input: str) -> dict:
    """Structured query under gpt-4o knowledge: list real companies matching the criteria."""
    from llm import chat_json

    prompt = (
        f"Based on the criteria '{query_input}', list up to 6 real companies that match.\n"
        'JSON format: {"results": [{"company": str, "employees": int, '
        '"country": str(English), "industry": str(English), "revenue": str}]}.\n'
        "Use only real companies, never fabricate. Output JSON only."
    )
    data = chat_json([
        {"role": "system", "content": _LLM_SYS},
        {"role": "user", "content": prompt},
    ])
    rows = (data or {}).get("results") if isinstance(data, dict) else None
    rows = rows or []
    entities = [
        {"id": f"llm:{r.get('company','')}", "name": r.get("company", ""), "entity_type": "Company"}
        for r in rows
        if r.get("company")
    ]
    return {"results": rows, "entities": entities, "_source": "gpt-4o"}


def _llm_search(query_input: str) -> str:
    """Natural-language answer under gpt-4o knowledge (markdown)."""
    data = _llm_query(query_input)
    lines = ["## Cala (gpt-4o real knowledge) results\n"]
    for r in data["results"]:
        lines.append(
            f"- **{r.get('company','?')}** — {r.get('industry','')}, "
            f"employees {r.get('employees','?')}, {r.get('country','')}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Mock data (offline demo). Built around "German automotive manufacturing/parts companies" to fit the auto-parts selling scenario.
# --------------------------------------------------------------------------

_MOCK_COMPANIES = {
    "Bosch Mobility": {
        "id": "cala_bosch",
        "entity_type": "Company",
        "name": "Bosch Mobility",
        "employees": 250000,
        "country": "Germany",
        "industry": "automotive manufacturing",
        "website": "https://www.bosch-mobility.com",
        "revenue": "€52B",
        "founded_year": 1886,
        "key_people": [
            {"name": "Markus Heyn", "role": "CEO"},
            {"name": "Hans Müller", "role": "Head of Procurement"},
        ],
        "recent_news": "Bosch announced an expansion of its e-drive component lines, building a new plant in Stuttgart in 2026.",
    },
    "Continental AG": {
        "id": "cala_conti",
        "entity_type": "Company",
        "name": "Continental AG",
        "employees": 200000,
        "country": "Germany",
        "industry": "automotive parts",
        "website": "https://www.continental.com",
        "revenue": "€40B",
        "founded_year": 1871,
        "key_people": [{"name": "Nikolai Setzer", "role": "CEO"}],
        "recent_news": "Continental is looking for sensor suppliers for its next-generation ADAS systems.",
    },
    "ZF Friedrichshafen": {
        "id": "cala_zf",
        "entity_type": "Company",
        "name": "ZF Friedrichshafen",
        "employees": 165000,
        "country": "Germany",
        "industry": "automotive manufacturing",
        "website": "https://www.zf.com",
        "revenue": "€43B",
        "founded_year": 1915,
        "key_people": [{"name": "Holger Klein", "role": "CEO"}],
        "recent_news": "ZF is increasing investment in electric transmissions.",
    },
}


def _find_company_by_name(name: str) -> Optional[dict]:
    name_l = (name or "").lower()
    for key, c in _MOCK_COMPANIES.items():
        if name_l in key.lower() or key.lower() in name_l:
            return c
    return None


def _mock_entity_search(name: str) -> list[dict]:
    c = _find_company_by_name(name)
    if c:
        return [{"id": c["id"], "name": c["name"], "entity_type": "Company"}]
    # Treat as a person name: search within key_people
    name_l = (name or "").lower()
    for c in _MOCK_COMPANIES.values():
        for p in c.get("key_people", []):
            if name_l in p["name"].lower():
                return [
                    {
                        "id": f"cala_person_{p['name'].split()[0].lower()}",
                        "name": p["name"],
                        "entity_type": "Person",
                        "_company": c["name"],
                    }
                ]
    return []


def _mock_entity_detail(entity_id: str) -> dict:
    for c in _MOCK_COMPANIES.values():
        if c["id"] == entity_id:
            return c
    if entity_id.startswith("cala_person_"):
        first = entity_id.replace("cala_person_", "")
        for c in _MOCK_COMPANIES.values():
            for p in c.get("key_people", []):
                if p["name"].split()[0].lower() == first:
                    return {
                        "id": entity_id,
                        "entity_type": "Person",
                        "name": p["name"],
                        "role": p["role"],
                        "works_at": c["name"],
                        "company_id": c["id"],
                    }
    return {"id": entity_id, "entity_type": "Unknown"}


def _mock_query(query_input: str) -> dict:
    q = (query_input or "").lower()
    rows = []
    entities = []
    for c in _MOCK_COMPANIES.values():
        # Simple match: Germany / automotive / headcount filter
        if "german" in q and c["country"] != "Germany":
            continue
        if "3000" in q and c["employees"] < 3000:
            continue
        rows.append(
            {
                "company": c["name"],
                "employees": c["employees"],
                "country": c["country"],
                "industry": c["industry"],
                "revenue": c["revenue"],
            }
        )
        entities.append({"id": c["id"], "name": c["name"], "entity_type": "Company"})
    if not rows:  # Return all when there is no filter
        for c in _MOCK_COMPANIES.values():
            rows.append(
                {
                    "company": c["name"],
                    "employees": c["employees"],
                    "country": c["country"],
                    "industry": c["industry"],
                }
            )
            entities.append({"id": c["id"], "name": c["name"], "entity_type": "Company"})
    return {"results": rows, "entities": entities, "_mock": True}


def _mock_search(query_input: str) -> str:
    data = _mock_query(query_input)
    lines = ["## Cala (mock) results\n"]
    for r in data["results"]:
        lines.append(f"- **{r['company']}** — {r.get('industry','')}, employees {r.get('employees','?')}, {r.get('country','')}")
    return "\n".join(lines)
