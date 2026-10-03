"""OpenAPI 3.0 离线目录编译库。"""

from .compiler import compile_catalog
from .errors import CatalogError, RefResolutionError, SourceLocation
from .graph import Catalog, Operation, Parameter, SchemaEdge, SchemaNode


def lookup(catalog: Catalog, method: str, path: str):
    return catalog.lookup(method, path)


__all__ = [
    "compile_catalog",
    "lookup",
    "Catalog",
    "Operation",
    "Parameter",
    "SchemaEdge",
    "SchemaNode",
    "CatalogError",
    "RefResolutionError",
    "SourceLocation",
]
