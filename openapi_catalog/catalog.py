"""Public catalog API: compile_catalog and lookup."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .compiler import Compiler
from .graph import Operation, Parameter, SchemaNode
from .jsonref import NodeId, join_pointer

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class Catalog:
    """Compiled catalog of operations plus the shared schema graph."""

    def __init__(self) -> None:
        self._operations: Dict[Tuple[str, str], Operation] = {}
        self._nodes: List[SchemaNode] = []

    @property
    def operations(self) -> List[Operation]:
        return list(self._operations.values())

    @property
    def nodes(self) -> List[SchemaNode]:
        return list(self._nodes)

    def lookup(self, method: str, path: str) -> Optional[Operation]:
        """Find the compiled operation for (method, path)."""
        return self._operations.get((method.lower(), path))


def compile_catalog(entry_file: str) -> Catalog:
    """Compile an OpenAPI 3.0 JSON document tree into a Catalog."""
    compiler = Compiler()
    doc_key, document = compiler.load_entry(entry_file)
    catalog = Catalog()

    paths = document.get("paths") if isinstance(document, dict) else None
    if not isinstance(paths, dict):
        catalog._nodes = compiler.nodes
        return catalog

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        base_pointer = join_pointer(join_pointer("", "paths"), path)
        inherited = path_item.get("parameters")
        inherited = inherited if isinstance(inherited, list) else []

        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            op_pointer = join_pointer(base_pointer, method)
            own = operation.get("parameters")
            own = own if isinstance(own, list) else []
            parameters = _merge_parameters(
                compiler, doc_key, inherited, own, base_pointer, op_pointer
            )
            response_schema = _response_schema(compiler, doc_key, op_pointer, operation)
            catalog._operations[(method, path)] = Operation(
                method=method,
                path=path,
                parameters=parameters,
                response_schema=response_schema,
            )

    catalog._nodes = compiler.nodes
    return catalog


def _merge_parameters(
    compiler: Compiler,
    doc_key,
    inherited: List,
    own: List,
    base_pointer: str,
    op_pointer: str,
) -> List[Parameter]:
    """Operation-level params override path-level ones by (name, in)."""
    merged: "Dict[Tuple[str, str], Tuple[object, str]]" = {}
    order: List[Tuple[str, str]] = []
    for params, pointer in ((inherited, base_pointer), (own, op_pointer)):
        for index, param in enumerate(params):
            if not isinstance(param, dict):
                continue
            name = param.get("name")
            location = param.get("in")
            if not isinstance(name, str) or not isinstance(location, str):
                continue
            key = (name, location)
            if key not in merged:
                order.append(key)
            param_pointer = join_pointer(join_pointer(pointer, "parameters"), str(index))
            merged[key] = (param, param_pointer)

    result: List[Parameter] = []
    for key in order:
        param, param_pointer = merged[key]
        schema = param.get("schema")
        schema_node = None
        if isinstance(schema, dict):
            schema_node = compiler.node_for(
                NodeId(doc_key, join_pointer(param_pointer, "schema"))
            )
        result.append(Parameter(name=key[0], location=key[1], schema=schema_node))
    return result


def _response_schema(
    compiler: Compiler, doc_key, op_pointer: str, operation: Dict
) -> Optional[SchemaNode]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    response = responses.get("200")
    if not isinstance(response, dict):
        return None
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return None
    pointer = join_pointer(op_pointer, "responses")
    pointer = join_pointer(pointer, "200")
    pointer = join_pointer(pointer, "content")
    pointer = join_pointer(pointer, "application/json")
    pointer = join_pointer(pointer, "schema")
    return compiler.node_for(NodeId(doc_key, pointer))
