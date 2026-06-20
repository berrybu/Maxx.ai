"""Maxx graph data structures -- triples + cognitive state."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

NODE_TYPES = ("person", "company", "us_company", "industry", "product", "email_thread", "topic",
              "deal", "employee", "activity")
EXTRACTORS = ("human", "LLM", "OCR", "Cala", "system")
STATUSES = ("proposed", "confirmed", "corrected", "retired")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Node:
    type: str
    label: str
    id: str = ""
    props: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("n")
        if self.type not in NODE_TYPES:
            raise ValueError(f"Node.type must be one of {NODE_TYPES}, got {self.type!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Node":
        return cls(type=d["type"], label=d["label"], id=d.get("id", ""), props=dict(d.get("props", {})))


@dataclass
class Edge:
    subject: str
    predicate: str
    object: Any
    source: str
    extractor: str
    confidence: float
    status: str = "proposed"
    id: str = ""
    t: float = 0.0
    supersedes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("e")
        if self.t == 0.0:
            self.t = time.time()
        if self.extractor not in EXTRACTORS:
            raise ValueError(f"Edge.extractor must be one of {EXTRACTORS}, got {self.extractor!r}")
        if self.status not in STATUSES:
            raise ValueError(f"Edge.status must be one of {STATUSES}, got {self.status!r}")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(f"Edge.confidence must be in [0,1], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Edge":
        return cls(
            subject=d["subject"], predicate=d["predicate"], object=d["object"],
            source=d["source"], extractor=d["extractor"], confidence=float(d["confidence"]),
            status=d["status"], id=d.get("id", ""), t=float(d.get("t", 0.0)), supersedes=d.get("supersedes"),
        )
