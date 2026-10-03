"""Cross-file references: same fragment names, dot segments, %-encoding,
pointers into property names containing slashes, and parameter override."""

import json
import os

import pytest

from openapi_catalog import compile_catalog


@pytest.fixture()
def catalog(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    api = {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/widgets": {
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "schema": {"$ref": "#/components/schemas/Widget"},
                    },
                    {
                        "name": "trace",
                        "in": "header",
                        "schema": {
                            "$ref": "../b/common%20schemas.json#/components/schemas/Widget"
                        },
                    },
                ],
                "get": {
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "schema": {
                                "$ref": "../b/./common%20schemas.json#/components/schemas/Widget"
                            },
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "../b/common%20schemas.json#/components/schemas/Gadget"
                                    }
                                }
                            },
                        }
                    },
                },
                "put": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Widget"}
                                }
                            },
                        }
                    }
                },
            }
        },
        "components": {
            "schemas": {
                "Widget": {"type": "string", "description": "entry widget"},
                "Gadget": {
                    "type": "object",
                    "properties": {
                        "a/b": {"type": "integer"},
                        "self": {
                            "$ref": "../b/./common%20schemas.json#/components/schemas/Gadget"
                        },
                    },
                },
            }
        },
    }
    common = {
        "components": {
            "schemas": {
                "Widget": {"type": "number", "description": "b widget"},
                "Gadget": {
                    "type": "object",
                    "properties": {
                        "back": {"$ref": "../a/api.json#/components/schemas/Gadget"},
                        "odd": {
                            "$ref": "../a/api.json#/components/schemas/Gadget/properties/a~1b"
                        },
                    },
                },
            }
        }
    }
    entry = dir_a / "api.json"
    entry.write_text(json.dumps(api), encoding="utf-8")
    (dir_b / "common schemas.json").write_text(json.dumps(common), encoding="utf-8")
    return compile_catalog(str(entry)), os.path.normpath(str(entry))


def _param(op, name, location):
    matches = [p for p in op.parameters if p.name == name and p.location == location]
    assert len(matches) == 1
    return matches[0]


def test_operation_param_overrides_and_inherits(catalog):
    cat, entry_path = catalog
    op = cat.lookup("get", "/widgets")
    assert op is not None

    # Operation-level q overrides the inherited one and lands in file b.
    q = _param(op, "q", "query")
    assert q.schema.id.doc.path != entry_path
    assert q.schema.id.doc.path.endswith(os.path.join("b", "common schemas.json"))
    assert q.schema.id.pointer == "/components/schemas/Widget"
    assert q.schema.schema["type"] == "number"

    # Inherited trace parameter survives and shares the exact same node.
    trace = _param(op, "trace", "header")
    assert trace.schema is q.schema


def test_same_fragment_names_in_different_files_stay_distinct(catalog):
    cat, entry_path = catalog
    put = cat.lookup("put", "/widgets")
    entry_widget = put.response_schema
    assert entry_widget.id.doc.path == entry_path
    assert entry_widget.id.pointer == "/components/schemas/Widget"
    assert entry_widget.schema["type"] == "string"

    get = cat.lookup("get", "/widgets")
    b_widget = _param(get, "q", "query").schema
    assert b_widget is not entry_widget
    assert b_widget.id.pointer == entry_widget.id.pointer  # same pointer, other file


def test_mutual_cross_file_recursion_is_finite(catalog):
    cat, entry_path = catalog
    get = cat.lookup("get", "/widgets")
    b_gadget = get.response_schema
    assert b_gadget.id.pointer == "/components/schemas/Gadget"
    assert b_gadget.id.doc.path != entry_path

    back = next(e for e in b_gadget.edges if e.label == "back")
    a_gadget = back.target
    assert a_gadget.id.doc.path == entry_path
    assert a_gadget.id.pointer == "/components/schemas/Gadget"

    self_edge = next(e for e in a_gadget.edges if e.label == "self")
    assert self_edge.target is b_gadget  # finite cycle, not unrolled


def test_pointer_into_slash_named_property(catalog):
    cat, entry_path = catalog
    get = cat.lookup("get", "/widgets")
    b_gadget = get.response_schema
    odd = next(e for e in b_gadget.edges if e.label == "odd")

    a_gadget = next(e for e in b_gadget.edges if e.label == "back").target
    slash_prop = next(e for e in a_gadget.edges if e.label == "a/b")
    assert slash_prop.target is odd.target
    assert slash_prop.target.schema["type"] == "integer"
    assert slash_prop.target.id.pointer.endswith("properties/a~1b")
