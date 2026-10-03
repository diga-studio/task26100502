"""compile_catalog 主实现：把 OpenAPI 3.0 文档编译为共享身份的有限模式图。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .errors import RefResolutionError, SourceLocation
from .graph import Catalog, Operation, Parameter, SchemaEdge, SchemaNode
from .resolver import DocumentStore, canonical_pointer, path_to_file_uri

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _child(location: SourceLocation, *tokens: str) -> SourceLocation:
    return SourceLocation(
        file_uri=location.file_uri,
        pointer=location.pointer + canonical_pointer(tuple(tokens)),
    )


class _GraphBuilder:
    """按规范化源位置内化（intern）模式节点，保证共享身份与有限图。"""

    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        self.nodes: Dict[Tuple[str, str], SchemaNode] = {}
        # 引用位置 -> 最终非引用模式位置（仅缓存成功解析）。
        self.ref_cache: Dict[Tuple[str, str], SourceLocation] = {}

    def node_for(self, location: SourceLocation) -> SchemaNode:
        target = self._follow_refs(location)
        key = (target.file_uri, target.pointer)
        node = self.nodes.get(key)
        if node is None:
            value = self._value_at(target, target, [])
            if not isinstance(value, dict):
                raise RefResolutionError(
                    "reference does not resolve to a schema object",
                    origin=location,
                )
            node = SchemaNode(location=target)
            self.nodes[key] = node  # 先注册再填充，合法递归共享同一节点
            self._populate(node, value, target)
        return node

    def _follow_refs(self, location: SourceLocation) -> SourceLocation:
        """沿连续 $ref 跳到最终非引用模式位置；检测纯引用环。"""
        visited: List[SourceLocation] = []
        current = location
        while True:
            cached = self.ref_cache.get((current.file_uri, current.pointer))
            if cached is not None:
                current = cached
                break
            value = self._value_at(current, location, visited)
            if isinstance(value, dict) and "$ref" in value:
                if current in visited:
                    raise RefResolutionError(
                        "pure $ref cycle: chain never reaches a non-reference schema",
                        origin=location,
                        chain=visited + [current],
                    )
                visited.append(current)
                try:
                    current = self.store.resolve_ref(current.file_uri, value["$ref"])
                except RefResolutionError as exc:
                    raise RefResolutionError(
                        exc.message, origin=location, chain=list(visited)
                    )
            else:
                break
        for hop in visited:
            self.ref_cache[(hop.file_uri, hop.pointer)] = current
        return current

    def _value_at(
        self, location: SourceLocation, origin: SourceLocation, chain: List[SourceLocation]
    ) -> Any:
        try:
            return self.store.resolve_location(location)
        except RefResolutionError as exc:
            raise RefResolutionError(exc.message, origin=origin, chain=list(chain))

    def _populate(self, node: SchemaNode, value: Dict[str, Any], location: SourceLocation) -> None:
        for field, field_value in value.items():
            if field == "properties" and isinstance(field_value, dict):
                for name in field_value:
                    self._add_edge(node, "property", location, ("properties", name), key=name)
            elif field == "items" and isinstance(field_value, dict):
                self._add_edge(node, "items", location, ("items",))
            elif field in ("allOf", "anyOf", "oneOf") and isinstance(field_value, list):
                for index in range(len(field_value)):
                    self._add_edge(
                        node, field, location, (field, str(index)), key=str(index)
                    )
            elif field == "not" and isinstance(field_value, dict):
                self._add_edge(node, "not", location, ("not",))
            elif field == "additionalProperties" and isinstance(field_value, dict):
                self._add_edge(
                    node, "additionalProperties", location, ("additionalProperties",)
                )
            else:
                # 其他字段原样保留；example/default/enum 中的 $ref 只是数据。
                node.attributes[field] = field_value

    def _add_edge(
        self,
        node: SchemaNode,
        kind: str,
        location: SourceLocation,
        tokens: Tuple[str, ...],
        key: Optional[str] = None,
    ) -> None:
        target = self.node_for(_child(location, *tokens))
        node.edges.append(SchemaEdge(kind=kind, source=node, target=target, key=key))


def _merge_parameters(
    builder: _GraphBuilder,
    path_loc: SourceLocation,
    op_loc: SourceLocation,
    inherited: List[Any],
    own: List[Any],
) -> List[Parameter]:
    """操作继承路径级 parameters，操作级以 (name, in) 覆盖。"""
    merged: List[Tuple[dict, SourceLocation]] = []
    slots: Dict[Tuple[Any, Any], int] = {}
    for index, param in enumerate(inherited):
        slots[(param.get("name"), param.get("in"))] = len(merged)
        merged.append((param, _child(path_loc, "parameters", str(index), "schema")))
    for index, param in enumerate(own):
        slot_key = (param.get("name"), param.get("in"))
        loc = _child(op_loc, "parameters", str(index), "schema")
        if slot_key in slots:
            merged[slots[slot_key]] = (param, loc)
        else:
            slots[slot_key] = len(merged)
            merged.append((param, loc))
    result: List[Parameter] = []
    for param, schema_loc in merged:
        schema_node = builder.node_for(schema_loc) if "schema" in param else None
        result.append(Parameter(param.get("name"), param.get("in"), schema_node))
    return result


def _response_schema(builder: _GraphBuilder, op_loc: SourceLocation, op: dict):
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None
    resp = responses.get("200")
    if not isinstance(resp, dict):
        return None
    content = resp.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict) or "schema" not in media:
        return None
    return builder.node_for(
        _child(op_loc, "responses", "200", "content", "application/json", "schema")
    )


def compile_catalog(entry_file: str) -> Catalog:
    """编译入口 JSON 文件为目录；引用问题抛 RefResolutionError。"""
    store = DocumentStore()
    entry_uri = path_to_file_uri(entry_file)
    store.load(entry_uri)
    builder = _GraphBuilder(store)
    catalog = Catalog()
    root = SourceLocation(entry_uri, "")
    doc = store.resolve_location(root)
    paths = doc.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_loc = _child(root, "paths", path)
        inherited = path_item.get("parameters") or []
        for method in METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            op_loc = _child(path_loc, method)
            parameters = _merge_parameters(
                builder, path_loc, op_loc, inherited, op.get("parameters") or []
            )
            catalog.operations[(method, path)] = Operation(
                method=method,
                path=path,
                parameters=parameters,
                response_schema=_response_schema(builder, op_loc, op),
            )
    catalog.nodes = builder.nodes
    return catalog
