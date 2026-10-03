"""跨目录互引、点段、百分号编码文件名、含斜杠属性名指针、参数覆盖。"""

import json
from pathlib import Path

from openapi_catalog import compile_catalog


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _build_tree(root: Path) -> Path:
    entry = root / "api" / "entry.json"
    common = root / "shared" / "common defs.json"
    petstore = root / "api" / "schemas" / "pet store.json"

    _write(
        entry,
        {
            "openapi": "3.0.0",
            "info": {"title": "t", "version": "1"},
            "paths": {
                "/things": {
                    "parameters": [
                        {
                            "name": "trace",
                            "in": "header",
                            "schema": {
                                "$ref": "../shared/common%20defs.json"
                                "#/components/schemas/Trace"
                            },
                        },
                        {
                            "name": "version",
                            "in": "query",
                            "schema": {"type": "string", "enum": ["v0"]},
                        },
                    ],
                    "get": {
                        "parameters": [
                            {
                                "name": "version",
                                "in": "query",
                                "schema": {
                                    "$ref": "../shared/common%20defs.json"
                                    "#/components/schemas/Slash/properties/a~1b"
                                },
                            },
                            {
                                "name": "limit",
                                "in": "query",
                                "schema": {"type": "integer"},
                            },
                        ],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "./schemas/pet%20store.json"
                                            "#/components/schemas/Pet"
                                        }
                                    }
                                },
                            }
                        },
                    },
                    "post": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "../shared/common%20defs.json"
                                            "#/components/schemas/Wrapper"
                                        }
                                    }
                                },
                            }
                        },
                    },
                }
            },
        },
    )
    _write(
        common,
        {
            "components": {
                "schemas": {
                    "Trace": {"type": "string", "pattern": "^[0-9a-f]+$"},
                    "Thing": {"type": "string", "description": "common thing"},
                    "Slash": {
                        "type": "object",
                        "properties": {"a/b": {"type": "integer", "minimum": 3}},
                    },
                    "Wrapper": {
                        "type": "object",
                        "properties": {
                            "pet": {
                                "$ref": "../api/schemas/pet%20store.json"
                                "#/components/schemas/Pet"
                            }
                        },
                    },
                }
            }
        },
    )
    _write(
        petstore,
        {
            "components": {
                "schemas": {
                    "Thing": {"type": "number", "description": "petstore thing"},
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "kind": {"$ref": "#/components/schemas/Thing"},
                            "tag": {
                                "$ref": "../../shared/common%20defs.json"
                                "#/components/schemas/Thing"
                            },
                            "name": {"type": "string"},
                        },
                    },
                }
            }
        },
    )
    return entry


def test_cross_directory_shared_identity_and_param_override(tmp_path):
    entry = _build_tree(tmp_path)
    catalog = compile_catalog(str(entry))
    op = catalog.lookup("get", "/things")
    assert op is not None

    # 参数合并：继承顺序保留，覆盖原位替换，新增追加。
    assert [p.name for p in op.parameters] == ["trace", "version", "limit"]

    trace, version, limit = op.parameters
    # 继承项连接到 common defs.json 中的 Trace。
    assert trace.schema.location.file_uri.endswith("/shared/common%20defs.json")
    assert trace.schema.location.pointer == "/components/schemas/Trace"
    assert trace.schema.attributes["pattern"] == "^[0-9a-f]+$"

    # 覆盖项连接到操作级 $ref：含斜杠属性名的指针目标。
    assert version.schema.location.pointer == "/components/schemas/Slash/properties/a~1b"
    assert version.schema.attributes == {"type": "integer", "minimum": 3}

    # 新增项为入口文件中的内联模式。
    assert limit.schema.location.file_uri.endswith("/api/entry.json")
    assert limit.schema.attributes == {"type": "integer"}

    # 响应根为 pet store.json 中的 Pet。
    pet = op.response_schema
    assert pet.location.file_uri.endswith("/api/schemas/pet%20store.json")
    assert pet.location.pointer == "/components/schemas/Pet"

    # Pet.tag 跨目录（点段 + 百分号编码）指向 common 的 Thing。
    tag = next(e for e in pet.edges if e.kind == "property" and e.key == "tag").target
    assert tag.location.file_uri.endswith("/shared/common%20defs.json")
    assert tag.location.pointer == "/components/schemas/Thing"
    assert tag.attributes["description"] == "common thing"

    # 两个目录的同名片段不混淆：Pet.kind 经同文件片段引用本地 Thing。
    petstore_thing = next(e for e in pet.edges if e.key == "kind").target
    assert petstore_thing.location.pointer == "/components/schemas/Thing"
    assert petstore_thing.location.file_uri == pet.location.file_uri
    assert petstore_thing is not tag
    assert petstore_thing.attributes["description"] == "petstore thing"

    # common 的 Wrapper.pet 反向引用同一 Pet 节点（互引共享身份）。
    wrapper = catalog.lookup("post", "/things").response_schema
    assert wrapper.location.file_uri.endswith("/shared/common%20defs.json")
    wrapper_pet = next(e for e in wrapper.edges if e.key == "pet").target
    assert wrapper_pet is pet
