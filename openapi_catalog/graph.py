"""Schema graph node types exposed by the compiled catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .jsonref import NodeId


@dataclass
class Edge:
    """A structural edge from a schema node to a child schema node."""

    kind: str  # 'property' | 'items' | 'allOf' | 'anyOf' | 'oneOf' | 'not' | 'additionalProperties'
    label: Optional[str]  # property name, index for composites, None otherwise
    target: "SchemaNode"


@dataclass
class SchemaNode:
    """One node per (document, pointer) schema position; shared by identity."""

    id: NodeId
    schema: Dict[str, Any] = field(default_factory=dict)  # non-ref fields, verbatim
    edges: List[Edge] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SchemaNode) and other.id == self.id


@dataclass
class Parameter:
    """An effective operation parameter (schema-only)."""

    name: str
    location: str  # 'query' | 'path' | 'header' | 'cookie'
    schema: Optional[SchemaNode]


@dataclass
class Operation:
    """A compiled operation."""

    method: str
    path: str
    parameters: List[Parameter] = field(default_factory=list)
    response_schema: Optional[SchemaNode] = None  # 200 application/json root
