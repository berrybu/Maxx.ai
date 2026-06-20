"""Product-doc RAG -- lets the email Agent "read technical docs". Switch scenario docs via the PRODUCT_DOC config."""

from __future__ import annotations

import os
import re
from functools import lru_cache

from config import get_settings

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DOC = os.path.join(_ROOT, "docs", "product_doc.md")


def _resolve_doc(doc_path=None):
    candidate = doc_path or get_settings().product_doc
    if not candidate:
        return _DEFAULT_DOC
    return candidate if os.path.isabs(candidate) else os.path.join(_ROOT, candidate)


@lru_cache(maxsize=8)
def _load_chunks(doc):
    if not os.path.exists(doc):
        return []
    text = open(doc, "r", encoding="utf-8").read()
    parts = re.split(r"\n(?=##\s)", text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        first_line = p.splitlines()[0]
        title = first_line.lstrip("#").strip()
        chunks.append((title, p))
    return chunks


def retrieve(query, *, k=3, doc_path=None):
    chunks = _load_chunks(_resolve_doc(doc_path))
    if not chunks:
        return ""
    terms = [t for t in re.split(r"\s+", (query or "").lower()) if len(t) > 1]
    scored = []
    for title, content in chunks:
        c_low = content.lower()
        score = sum(c_low.count(t) for t in terms)
        if any(key in title.lower() for key in ("value", "pain", "core product")):
            score += 1
        scored.append((score, title, content))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for s, t, c in scored[:k]]
    return "\n\n---\n\n".join(top)


def full_doc(doc_path=None):
    doc = _resolve_doc(doc_path)
    if not os.path.exists(doc):
        return ""
    return open(doc, "r", encoding="utf-8").read()
