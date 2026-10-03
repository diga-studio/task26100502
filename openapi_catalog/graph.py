"""编译结果的可遍历图结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .errors import SourceLocation


@dataclass
class SchemaNode:
    """图中的一个模式节点。同一规范化 (file_uri, pointer) 只对应一个实例。"""

    location: SourceLocation
    # 非引用模式的原始字段（properties/items/allOf/... 之外原样保留，
    # 这些结构字段的值以边表达，不出现在 attributes 中）。
    attributes: Dict[str, Any] = field(default_factory=dict)
    edges: List["SchemaEdge"] = field(default_factory=list)

    def targets(self, kind: Optional[str] = None) -> List["SchemaNode"]:
        return [e.target for e in self.edges if kind is None or e.kind == kind]


@dataclass
class SchemaEdge:
    """从源节点指向目标节点的结构边。kind ∈
    property/items/allOf/anyOf/oneOf/not/additionalProperties。"""

    kind: str
    source: SchemaNode
    target: SchemaNode
    key: Optional[str] = None  # property 名或组合下标


@dataclass
class Parameter:
    name: str
    in_: str
    schema: SchemaNode


@dataclass
class Operation:
    method: str
    path: str
    parameters: List[Parameter]
    response_schema: Optional[SchemaNode]  # 200 application/json 模式根


@dataclass
class Catalog:
    operations: Dict[Tuple[str, str], Operation] = field(default_factory=dict)
    nodes: Dict[Tuple[str, str], SchemaNode] = field(default_factory=dict)

    def lookup(self, method: str, path: str) -> Optional[Operation]:
        return self.operations.get((method.lower(), path))
