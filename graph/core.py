"""GraphCore -- the single source of truth for the Maxx CRM graph."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from .models import Edge, Node


class GraphCore:
    def __init__(self, store_path: Optional[str] = None) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._store_path = store_path

    def load(self) -> bool:
        if not self._store_path or not os.path.exists(self._store_path):
            return False
        with open(self._store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._nodes = {n["id"]: Node.from_dict(n) for n in data.get("nodes", [])}
        self._edges = {e["id"]: Edge.from_dict(e) for e in data.get("edges", [])}
        return True

    def save(self) -> None:
        if not self._store_path:
            return
        data = self.snapshot()
        tmp = self._store_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._store_path)

    def snapshot(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self._nodes.values()], "edges": [e.to_dict() for e in self._edges.values()]}

    def load_objects(self, nodes: list[Node], edges: list[Edge]) -> None:
        for n in nodes:
            self._nodes[n.id] = n
        for e in edges:
            self._edges[e.id] = e
        self.save()

    def query(self, *, node_type=None, status=None, subject=None, predicate=None, object=None, min_confidence=None) -> list[Edge]:
        results = []
        for e in self._edges.values():
            if status is not None and e.status != status:
                continue
            if subject is not None and e.subject != subject:
                continue
            if predicate is not None and e.predicate != predicate:
                continue
            if object is not None and e.object != object:
                continue
            if min_confidence is not None and e.confidence < min_confidence:
                continue
            if node_type is not None:
                subj = self._nodes.get(e.subject)
                if subj is None or subj.type != node_type:
                    continue
            results.append(e)
        return results

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def find_node(self, *, node_type=None, label=None) -> Optional[Node]:
        label_l = label.lower() if label else None
        for n in self._nodes.values():
            if node_type is not None and n.type != node_type:
                continue
            if label_l is not None and n.label.lower() != label_l:
                continue
            return n
        return None

    def list_nodes(self, *, node_type=None) -> list[Node]:
        nodes = list(self._nodes.values())
        if node_type is not None:
            nodes = [n for n in nodes if n.type == node_type]
        return nodes

    def get_edge(self, edge_id: str) -> Optional[Edge]:
        return self._edges.get(edge_id)

    def prop(self, node_id: str, predicate: str, *, default: Any = None) -> Any:
        edges = [e for e in self._edges.values() if e.subject == node_id and e.predicate == predicate and e.status != "retired"]
        if not edges:
            return default
        edges.sort(key=lambda e: e.t)
        return edges[-1].object

    def upsert_node(self, node: Node) -> Node:
        self._nodes[node.id] = node
        self.save()
        return node

    def delete_node(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)
        to_del = [eid for eid, e in self._edges.items() if e.subject == node_id or e.object == node_id]
        for eid in to_del:
            del self._edges[eid]
        self.save()

    def propose(self, edge: Edge) -> Edge:
        edge.status = "proposed"
        edge.t = time.time()
        self._edges[edge.id] = edge
        self.save()
        return edge

    def add_confirmed(self, edge: Edge) -> Edge:
        edge.status = "confirmed"
        edge.t = time.time()
        self._edges[edge.id] = edge
        self.save()
        return edge

    def confirm(self, edge_id: str) -> Edge:
        edge = self._require_edge(edge_id)
        edge.status = "confirmed"
        edge.t = time.time()
        self.save()
        return edge

    def correct(self, edge_id: str, new_fields: dict[str, Any]) -> Edge:
        old = self._require_edge(edge_id)
        old.status = "retired"
        old.t = time.time()
        protected = {"id", "status", "supersedes", "t"}
        merged = {"subject": old.subject, "predicate": old.predicate, "object": old.object,
                  "source": old.source, "extractor": old.extractor, "confidence": old.confidence}
        for k, v in new_fields.items():
            if k in protected:
                continue
            merged[k] = v
        new_edge = Edge(subject=merged["subject"], predicate=merged["predicate"], object=merged["object"],
                        source=merged["source"], extractor=merged["extractor"], confidence=float(merged["confidence"]),
                        status="corrected", supersedes=old.id)
        self._edges[new_edge.id] = new_edge
        self.save()
        return new_edge

    def retire(self, edge_id: str) -> Edge:
        edge = self._require_edge(edge_id)
        edge.status = "retired"
        edge.t = time.time()
        self.save()
        return edge

    def decay_scan(self, now: float, *, threshold_days: int = 90) -> list[Edge]:
        cutoff = now - threshold_days * 86400
        return [e for e in self._edges.values() if e.status in ("confirmed", "corrected") and e.t < cutoff]

    def _require_edge(self, edge_id: str) -> Edge:
        edge = self._edges.get(edge_id)
        if edge is None:
            raise KeyError(f"edge not found: {edge_id}")
        return edge
