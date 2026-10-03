"""500 operations sharing a 40-layer schema graph: identity, edge and node
counts must reflect real sharing, not unrolling."""

import json
import time

from openapi_catalog import compile_catalog

LAYERS = 40
OPERATIONS = 500
PARAMS_PER_OP = 10  # 500 ops x 10 params = 5000 shared schema positions


def _build_entry(tmp_path):
    schemas = {}
    for level in range(LAYERS - 1):
        schemas[f"L{level}"] = {
            "type": "object",
            "properties": {
                "left": {"$ref": f"#/components/schemas/L{level + 1}"},
                "right": {"$ref": f"#/components/schemas/L{level + 1}"},
            },
        }
    schemas[f"L{LAYERS - 1}"] = {"type": "string"}

    paths = {}
    for index in range(OPERATIONS):
        paths[f"/op{index}"] = {
            "get": {
                "parameters": [
                    {
                        "name": f"p{k}",
                        "in": "query",
                        "schema": {"$ref": f"#/components/schemas/L{k}"},
                    }
                    for k in range(PARAMS_PER_OP)
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/L0"}
                            }
                        },
                    }
                },
            }
        }

    doc = {
        "openapi": "3.0.0",
        "info": {"title": "scale", "version": "1"},
        "paths": paths,
        "components": {"schemas": schemas},
    }
    entry = tmp_path / "api.json"
    entry.write_text(json.dumps(doc), encoding="utf-8")
    return str(entry)


def test_shared_graph_identity_and_counts(tmp_path):
    entry = _build_entry(tmp_path)
    start = time.monotonic()
    cat = compile_catalog(entry)
    elapsed = time.monotonic() - start
    assert elapsed < 10, f"compilation too slow ({elapsed:.2f}s), sharing broken?"

    # Exactly one node per layer position: no unrolling of the 2-edge layers.
    assert len(cat.nodes) == LAYERS
    node_ids = {node.id for node in cat.nodes}
    assert len(node_ids) == LAYERS

    # Edge count is linear: 2 per non-leaf layer.
    total_edges = sum(len(node.edges) for node in cat.nodes)
    assert total_edges == 2 * (LAYERS - 1)

    # All 500 operations share the identical root node object.
    roots = [cat.lookup("get", f"/op{i}").response_schema for i in range(OPERATIONS)]
    assert all(root is roots[0] for root in roots)
    assert roots[0].id.pointer == "/components/schemas/L0"

    # The 5000 parameter positions collapse onto the same shared nodes.
    first = cat.lookup("get", "/op0")
    last = cat.lookup("get", f"/op{OPERATIONS - 1}")
    assert len(first.parameters) == PARAMS_PER_OP
    for k in range(PARAMS_PER_OP):
        assert first.parameters[k].schema is last.parameters[k].schema
        assert first.parameters[k].schema.id.pointer == f"/components/schemas/L{k}"

    # Both layer edges converge on the single next-layer node.
    layer0 = roots[0]
    left = next(e for e in layer0.edges if e.label == "left")
    right = next(e for e in layer0.edges if e.label == "right")
    assert left.target is right.target
    assert left.target.id.pointer == "/components/schemas/L1"
