"""Core compiler: loads documents and builds the shared schema graph."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from .errors import RefChainEntry, RefResolutionError, SourceLocation
from .graph import Edge, SchemaNode
from .jsonref import (
    DocKey,
    NodeId,
    join_pointer,
    normalize_doc_path,
    parse_fragment,
    resolve_pointer,
    split_ref,
)

_COMPOSITE_KINDS = ("allOf", "anyOf", "oneOf")


class Compiler:
    """Compiles a set of JSON documents into a shared schema graph."""

    def __init__(self) -> None:
        self._docs: Dict[DocKey, object] = {}
        self._nodes: Dict[NodeId, SchemaNode] = {}

    # -- document loading -------------------------------------------------

    def load_doc(self, key: DocKey, chain: List[RefChainEntry]) -> object:
        """Parse a document at most once per compilation."""
        if key not in self._docs:
            try:
                with open(key.path, "r", encoding="utf-8") as handle:
                    self._docs[key] = json.load(handle)
            except (OSError, ValueError) as exc:
                origin = chain[-1].at if chain else SourceLocation(key.path, "")
                raise RefResolutionError(
                    f"cannot load referenced document {key.path!r}: {exc}",
                    origin=origin,
                    chain=chain,
                ) from exc
        return self._docs[key]

    def load_entry(self, path: str) -> Tuple[DocKey, object]:
        """Load the entry document (must exist)."""
        key = DocKey(os.path.abspath(os.path.normpath(path)))
        return key, self.load_doc(key, [])

    # -- reference resolution ---------------------------------------------

    def _resolve_ref(self, site: NodeId, ref: str) -> NodeId:
        file_part, fragment = split_ref(ref)
        if file_part:
            target_doc = DocKey(normalize_doc_path(os.path.dirname(site.doc.path), file_part))
        else:
            target_doc = site.doc
        return NodeId(target_doc, parse_fragment(fragment))

    def _raw_at(self, node_id: NodeId, chain: List[RefChainEntry]) -> object:
        doc = self.load_doc(node_id.doc, chain)
        try:
            return resolve_pointer(doc, node_id.pointer)
        except (KeyError, IndexError, ValueError) as exc:
            origin = chain[-1].at if chain else SourceLocation(node_id.doc.path, node_id.pointer)
            raise RefResolutionError(
                f"missing ref target {node_id}",
                origin=origin,
                chain=chain,
            ) from exc

    # -- graph construction -------------------------------------------------

    def node_for(
        self, node_id: NodeId, chain: List[RefChainEntry] | None = None
    ) -> SchemaNode:
        """Return the shared node for a schema position, creating it once."""
        node = self._nodes.get(node_id)
        if node is not None:
            return node

        chain = list(chain or [])
        seen = {node_id}
        current = node_id
        while True:
            raw = self._raw_at(current, chain)
            if not (isinstance(raw, dict) and "$ref" in raw):
                break
            if not isinstance(raw.get("$ref"), str):
                raise RefResolutionError(
                    f"invalid $ref at {current}",
                    origin=SourceLocation(current.doc.path, current.pointer),
                    chain=chain,
                )
            chain.append(
                RefChainEntry(
                    at=SourceLocation(current.doc.path, current.pointer),
                    ref=raw["$ref"],
                )
            )
            target = self._resolve_ref(current, raw["$ref"])
            if target in seen:
                raise RefResolutionError(
                    "pure $ref cycle (no concrete schema reachable)",
                    origin=chain[0].at,
                    chain=chain,
                )
            seen.add(target)
            node = self._nodes.get(target)
            if node is not None:
                return node
            current = target

        if not isinstance(raw, dict):
            raise RefResolutionError(
                f"ref target is not a schema object: {current}",
                origin=chain[-1].at if chain else SourceLocation(current.doc.path, current.pointer),
                chain=chain,
            )

        node = SchemaNode(id=current, schema=raw)
        self._nodes[current] = node
        self._build_edges(node, raw)
        return node

    def _build_edges(self, node: SchemaNode, raw: Dict) -> None:
        def child(suffix: str) -> NodeId:
            return NodeId(node.id.doc, node.id.pointer + suffix)

        properties = raw.get("properties")
        if isinstance(properties, dict):
            for name in properties:
                node.edges.append(
                    Edge("property", name, self.node_for(child(join_pointer("/properties", name))))
                )

        items = raw.get("items")
        if isinstance(items, dict):
            node.edges.append(Edge("items", None, self.node_for(child("/items"))))

        for kind in _COMPOSITE_KINDS:
            members = raw.get(kind)
            if isinstance(members, list):
                for index, member in enumerate(members):
                    if isinstance(member, dict):
                        node.edges.append(
                            Edge(
                                kind,
                                str(index),
                                self.node_for(child(join_pointer("/" + kind, str(index)))),
                            )
                        )

        not_schema = raw.get("not")
        if isinstance(not_schema, dict):
            node.edges.append(Edge("not", None, self.node_for(child("/not"))))

        additional = raw.get("additionalProperties")
        if isinstance(additional, dict):
            node.edges.append(
                Edge("additionalProperties", None, self.node_for(child("/additionalProperties")))
            )

    @property
    def nodes(self) -> List[SchemaNode]:
        return list(self._nodes.values())
