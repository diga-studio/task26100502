"""500 个操作共享 40 层菱形引用图：节点身份、边数与节点数均为线性。"""

import json
from pathlib import Path

from openapi_catalog import compile_catalog

LAYERS = 40
OPERATIONS = 500


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc), encoding="utf-8")


def _build_tree(root: Path) -> Path:
    schemas = {}
    for i in range(LAYERS - 1):
        nxt = f"#/components/schemas/L{i + 1}"
        schemas[f"L{i}"] = {
            "type": "object",
            "properties": {"left": {"$ref": nxt}, "right": {"$ref": nxt}},
        }
    schemas[f"L{LAYERS - 1}"] = {"type": "string"}
    _write(root / "shared.json", {"components": {"schemas": schemas}})

    paths = {}
    for n in range(OPERATIONS):
        paths[f"/op{n}"] = {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "./shared.json#/components/schemas/L0"}
                            }
                        },
                    }
                }
            }
        }
    entry = root / "entry.json"
    _write(
        entry,
        {"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "paths": paths},
    )
    return entry


def test_shared_graph_identity_and_counts(tmp_path):
    entry = _build_tree(tmp_path)
    catalog = compile_catalog(str(entry))

    assert len(catalog.operations) == OPERATIONS

    # 500 个操作的响应根是同一个节点对象。
    roots = [catalog.lookup("get", f"/op{n}").response_schema for n in range(OPERATIONS)]
    assert all(root is roots[0] for root in roots)
    assert roots[0].location.pointer == "/components/schemas/L0"

    # 菱形引用被内化为线性数量的节点：恰好 40 个。
    assert len(catalog.nodes) == LAYERS

    # 每层两条边指向同一个下一层节点；总边数 2 * (LAYERS - 1)。
    total_edges = 0
    layer = roots[0]
    for i in range(LAYERS - 1):
        assert len(layer.edges) == 2
        left, right = layer.edges
        assert {left.kind, right.kind} == {"property"}
        assert {left.key, right.key} == {"left", "right"}
        assert left.target is right.target
        assert left.target.location.pointer == f"/components/schemas/L{i + 1}"
        total_edges += 2
        layer = left.target
    assert layer.edges == []
    assert layer.attributes == {"type": "string"}
    assert total_edges == 2 * (LAYERS - 1)
    assert sum(len(n.edges) for n in catalog.nodes.values()) == total_edges
