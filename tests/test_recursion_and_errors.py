"""别名递归、纯引用环、伪引用与忽略字段、缺失引用的可定位错误。"""

import json
from pathlib import Path

import pytest

from openapi_catalog import compile_catalog
from openapi_catalog.errors import RefResolutionError


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _entry(schema_ref: str) -> dict:
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
                                "application/json": {"schema": {"$ref": schema_ref}}
                            },
                        }
                    }
                }
            }
        },
    }


def test_two_level_alias_self_recursion(tmp_path):
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/AliasA"),
            "components": {
                "schemas": {
                    "AliasA": {"$ref": "#/components/schemas/AliasB"},
                    "AliasB": {"$ref": "#/components/schemas/Node"},
                    "Node": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                            "next": {"$ref": "#/components/schemas/AliasA"},
                        },
                    },
                }
            },
        },
    )
    catalog = compile_catalog(str(entry))
    root = catalog.lookup("get", "/x").response_schema
    # 两级别名最终到达 Node；Node 是唯一节点。
    assert root.location.pointer == "/components/schemas/Node"
    nxt = next(e for e in root.edges if e.kind == "property" and e.key == "next")
    assert nxt.target is root
    assert len(catalog.nodes) == 2  # Node + 内联 value 字符串


def test_pure_ref_cycle_fails_with_chain(tmp_path):
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/X"),
            "components": {
                "schemas": {
                    "X": {"$ref": "#/components/schemas/Y"},
                    "Y": {"$ref": "#/components/schemas/X"},
                }
            },
        },
    )
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(str(entry))
    err = excinfo.value
    assert "cycle" in err.message
    # 引用链可定位：从响应处的 $ref 出发，经过 X、Y 并回到 X。
    pointers = [loc.pointer for loc in err.chain]
    assert pointers == [
        "/paths/~1x/get/responses/200/content/application~1json/schema",
        "/components/schemas/X",
        "/components/schemas/Y",
        "/components/schemas/X",
    ]
    assert err.origin is not None


def test_cross_file_pure_ref_cycle_fails(tmp_path):
    other = tmp_path / "other.json"
    _write(other, {"components": {"schemas": {"B": {"$ref": "./entry.json#/components/schemas/A"}}}})
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/A"),
            "components": {"schemas": {"A": {"$ref": "./other.json#/components/schemas/B"}}},
        },
    )
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(str(entry))
    files = {loc.file_uri for loc in excinfo.value.chain}
    assert len(files) == 2  # 环跨越两个文件


def test_fake_ref_in_example_and_ignored_siblings(tmp_path):
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/Real"),
            "components": {
                "schemas": {
                    "Real": {
                        "type": "object",
                        "properties": {
                            # example/default/enum 中的 $ref 只是数据，不触发读取。
                            "a": {
                                "type": "string",
                                "example": {"$ref": "no/such/file.json#/x"},
                                "default": {"$ref": "#/components/schemas/Missing"},
                                "enum": [{"$ref": "./nowhere.json"}],
                            },
                            # $ref 对象的兄弟字段被忽略：其中的坏引用不生效。
                            "b": {
                                "$ref": "#/components/schemas/Target",
                                "description": "ignored",
                                "properties": {"evil": {"$ref": "missing.json#/x"}},
                                "items": {"$ref": "missing.json#/y"},
                            },
                        },
                    },
                    "Target": {"type": "integer"},
                }
            },
        },
    )
    catalog = compile_catalog(str(entry))
    root = catalog.lookup("get", "/x").response_schema
    a = next(e for e in root.edges if e.key == "a").target
    # 伪引用原样保留在属性里。
    assert a.attributes["example"] == {"$ref": "no/such/file.json#/x"}
    assert a.attributes["enum"] == [{"$ref": "./nowhere.json"}]
    b = next(e for e in root.edges if e.key == "b").target
    assert b.location.pointer == "/components/schemas/Target"
    assert b.attributes == {"type": "integer"}


def test_missing_pointer_target_error_is_locatable(tmp_path):
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/Wrapper"),
            "components": {
                "schemas": {
                    "Wrapper": {
                        "type": "object",
                        "properties": {
                            "broken": {"$ref": "#/components/schemas/Nope"}
                        },
                    }
                }
            },
        },
    )
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(str(entry))
    err = excinfo.value
    assert "Nope" in err.message
    # 发起位置是 broken 属性中的 $ref 对象。
    assert err.origin.pointer == "/components/schemas/Wrapper/properties/broken"
    assert err.origin.file_uri.endswith("/entry.json")
    assert [loc.pointer for loc in err.chain] == [
        "/components/schemas/Wrapper/properties/broken"
    ]


def test_missing_file_error_is_locatable(tmp_path):
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            **_entry("#/components/schemas/Wrapper"),
            "components": {
                "schemas": {
                    "Wrapper": {
                        "type": "object",
                        "properties": {
                            "broken": {"$ref": "./ghost.json#/components/schemas/G"}
                        },
                    }
                }
            },
        },
    )
    with pytest.raises(RefResolutionError) as excinfo:
        compile_catalog(str(entry))
    err = excinfo.value
    assert "ghost.json" in err.message
    assert err.origin.pointer == "/components/schemas/Wrapper/properties/broken"


def test_pointer_array_index_and_whole_document_ref(tmp_path):
    # 无片段引用整份文档：shared.json 本身即一个模式。
    _write(
        tmp_path / "shared.json",
        {
            "type": "object",
            "properties": {
                "choice": {
                    "allOf": [
                        {"type": "string"},
                        {"type": "string", "maxLength": 5},
                    ]
                }
            },
        },
    )
    entry = tmp_path / "entry.json"
    _write(
        entry,
        {
            "openapi": "3.0.0",
            "info": {"title": "t", "version": "1"},
            "paths": {
                "/x": {
                    "get": {
                        "parameters": [
                            {
                                "name": "q",
                                "in": "query",
                                # 数组下标指针：allOf 的第二个元素。
                                "schema": {
                                    "$ref": "./shared.json#/properties/choice/allOf/1"
                                },
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "./shared.json"}
                                    }
                                },
                            }
                        },
                    }
                }
            },
        },
    )
    catalog = compile_catalog(str(entry))
    op = catalog.lookup("get", "/x")
    # 整份文档引用：指针为空字符串。
    assert op.response_schema.location.pointer == ""
    assert op.response_schema.location.file_uri.endswith("/shared.json")
    # 数组下标定位到 allOf[1]。
    q = op.parameters[0]
    assert q.schema.location.pointer == "/properties/choice/allOf/1"
    assert q.schema.attributes == {"type": "string", "maxLength": 5}
    # 响应根中的 allOf 边与参数共享同一节点。
    choice = next(e for e in op.response_schema.edges if e.key == "choice").target
    allof1 = next(e for e in choice.edges if e.kind == "allOf" and e.key == "1").target
    assert allof1 is q.schema
