# task26100502

OpenAPI 3.0 离线目录编译库（纯 Python 标准库实现，无第三方依赖）。

## 用法

```python
from openapi_catalog import compile_catalog

catalog = compile_catalog("api.json")          # 只接受本地 JSON 文件
op = catalog.lookup("get", "/widgets")         # -> Operation | None

for param in op.parameters:                    # 有效参数（路径级继承 + 操作级覆盖）
    print(param.name, param.location, param.schema)

root = op.response_schema                      # 200 application/json 模式根节点
for edge in root.edges:                        # 可遍历的结构边
    print(edge.kind, edge.label, edge.target.id)
```

- `SchemaNode`：每个规范化 `(文件, JSON Pointer)` 位置恰好一个节点，任意引用路径下共享身份；合法递归表现为有限图中的环。
- `$ref` 支持本文件片段与相对文件引用（以出现 `$ref` 的文档为基准），正确处理点路径、百分号编码、`~0`/`~1` 与数组下标。
- 缺失目标与纯引用环使编译失败，抛出带发起位置与完整引用链的 `RefResolutionError`。

## 测试

```sh
python3 -m pytest tests/ -q
```
