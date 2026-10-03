"""Recursion legality, pure ref cycles, ignored $ref lookalikes, and
traceable errors for missing targets."""

import json

import pytest

from openapi_catalog import RefResolutionError, compile_catalog


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def _api(schemas, response_ref):
    return {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/x": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {"schema": {"$ref": response_ref}}
                            },
                        }
                    }
                }
            }
        },
        "components": {"schemas": schemas},
    }


def test_self_recursion_through_two_alias_levels(tmp_path):
    schemas = {
        "AliasOne": {"$ref": "#/components/schemas/AliasTwo"},
        "AliasTwo": {"$ref": "#/components/schemas/Node"},
        "Node": {
            "type": "object",
            "properties": {
                "child": {"$ref": "#/components/schemas/AliasOne"},
                "value": {"type": "integer"},
            },
        },
    }
    entry = _write(tmp_path, "api.json", _api(schemas, "#/components/schemas/AliasOne"))
    cat = compile_catalog(entry)

    root = cat.lookup("get", "/x").response_schema
    assert root.id.pointer == "/components/schemas/Node"
    child = next(e for e in root.edges if e.label == "child")
    assert child.target is root  # finite graph, shared identity
    value = next(e for e in root.edges if e.label == "value")
    assert value.target.schema["type"] == "integer"
    # Alias positions collapse onto the single concrete node (+ value node).
    assert len(cat.nodes) == 2


def test_pure_ref_cycle_fails_with_chain(tmp_path):
    schemas = {
        "LoopA": {"$ref": "#/components/schemas/LoopB"},
        "LoopB": {"$ref": "#/components/schemas/LoopA"},
    }
    entry = _write(tmp_path, "api.json", _api(schemas, "#/components/schemas/LoopA"))
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(entry)
    message = str(excinfo.value)
    assert "LoopA" in message and "LoopB" in message
    assert excinfo.value.chain, "error must carry the ref chain"
    assert any("LoopB" in entry.ref for entry in excinfo.value.chain)


def test_fake_refs_in_example_and_ignored_siblings_trigger_no_reads(tmp_path):
    schemas = {
        "Real": {"type": "string"},
        "WithData": {
            "type": "object",
            "example": {"$ref": "ghost/never.json#/nope"},
            "default": {"$ref": "ghost/never.json"},
            "enum": [{"$ref": "#/components/schemas/DoesNotExist"}],
            "properties": {"ok": {"$ref": "#/components/schemas/Real"}},
        },
        "RefWithSiblings": {
            "$ref": "#/components/schemas/Real",
            "description": "ignored sibling",
            "properties": {"evil": {"$ref": "ghost/never.json#/x"}},
            "items": {"$ref": "ghost/never.json#/y"},
        },
    }
    api = _api(schemas, "#/components/schemas/WithData")
    api["paths"]["/y"] = {
        "get": {
            "responses": {
                "200": {
                    "description": "ok",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/RefWithSiblings"}
                        }
                    },
                }
            }
        }
    }
    entry = _write(tmp_path, "api.json", api)
    cat = compile_catalog(entry)  # must not try to read ghost/never.json

    with_data = cat.lookup("get", "/x").response_schema
    assert with_data.schema["example"] == {"$ref": "ghost/never.json#/nope"}
    ok = next(e for e in with_data.edges if e.label == "ok")
    via_alias = cat.lookup("get", "/y").response_schema
    assert via_alias is ok.target  # siblings of $ref ignored, alias collapses
    assert via_alias.schema["type"] == "string"


def test_missing_file_ref_error_is_traceable(tmp_path):
    schemas = {"Broken": {"$ref": "ghost/missing.json#/components/schemas/X"}}
    entry = _write(tmp_path, "api.json", _api(schemas, "#/components/schemas/Broken"))
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(entry)
    message = str(excinfo.value)
    assert "missing.json" in message
    # The chain starts at the response schema position that began resolution
    # and ends at the ref site that pointed into the missing file.
    assert excinfo.value.chain[0].at.pointer.startswith("/paths/")
    assert "missing.json" in excinfo.value.chain[-1].ref


def test_missing_pointer_ref_error_is_traceable(tmp_path):
    schemas = {"Broken": {"$ref": "#/components/schemas/NotThere"}}
    entry = _write(tmp_path, "api.json", _api(schemas, "#/components/schemas/Broken"))
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(entry)
    assert "NotThere" in str(excinfo.value)
    assert any("NotThere" in hop.ref for hop in excinfo.value.chain)
