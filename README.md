# openapi-catalog

OpenAPI 3.0 离线目录编译库：只接收本地 JSON 文件，把入口文档及其相对引用
编译为**共享身份的有限模式图**，并提供操作查询。

## API

```python
from openapi_catalog import compile_catalog, lookup

catalog = compile_catalog("path/to/entry.json")
op = catalog.lookup("get", "/pets")        # 或 lookup(catalog, "get", "/pets")
op.parameters                              # [Parameter(name, in_, schema)]
op.response_schema                         # 200 application/json 的模式根节点
```

返回类型（`openapi_catalog.graph`）：

- `Catalog`：`operations[(method, path)] -> Operation`，`nodes[(file_uri, pointer)] -> SchemaNode`。
- `SchemaNode`：`location`（规范化 `file_uri#pointer`）、`attributes`（非结构字段原样保留）、
  `edges`（`SchemaEdge(kind, source, target, key)`，`kind` ∈
  `property/items/allOf/anyOf/oneOf/not/additionalProperties`）。

## 语义要点

- 操作继承路径级 `parameters`，操作级以 `(name, in)` 覆盖，未覆盖项保留。
- 相对引用以出现 `$ref` 的文档为基准；支持点段、百分号编码文件名、
  JSON Pointer 的 `~0`/`~1` 与数组下标；无片段表示整份文档。
- 同一规范化 `(file_uri, pointer)` 只产生一个节点：合法递归是有限图，
  引用别名（连续 `$ref` 跳）共享最终非引用模式的节点。
- 纯引用环（沿 `$ref` 永远到不了非引用模式）与缺失目标使编译失败，
  抛出 `RefResolutionError`，携带 `origin`（发起位置）与 `chain`（引用链）。
- 引用对象忽略 `$ref` 之外的字段；`example`/`default`/`enum` 中的 `$ref` 只是数据。
- 同一文件每次编译最多解析一次；共享子图按位置内化，节点与边数量线性。

## 测试

```bash
python3 -m pytest tests/ -q
```
