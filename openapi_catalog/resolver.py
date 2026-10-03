"""文档加载与 $ref 解析：URI 归一化、JSON Pointer、文档缓存。"""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from .errors import RefResolutionError, SourceLocation


def path_to_file_uri(path: str) -> str:
    """把本地文件路径转为规范化 file:// URI。"""
    return _canonical_file_uri(Path(path).as_uri())


def _canonical_file_uri(uri: str) -> str:
    """归一化 file URI：解码百分号、折叠点段，保证同一文件只有一个键。"""
    parts = urlsplit(uri)
    if parts.scheme not in ("", "file"):
        raise RefResolutionError(f"unsupported URI scheme: {parts.scheme or uri}")
    path = unquote(parts.path)
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = "/" + path
    return Path(path).resolve().as_uri()


def parse_pointer(fragment: str) -> Tuple[str, ...]:
    """解析 URI 片段中的 JSON Pointer（RFC 6901 片段表示）。

    先百分号解码，再按 '/' 切分，最后处理 ~0/~1 转义。
    空片段表示整份文档。
    """
    fragment = unquote(fragment)
    if fragment == "":
        return ()
    if not fragment.startswith("/"):
        raise RefResolutionError(f"unsupported fragment (not a JSON Pointer): #{fragment}")
    tokens = fragment.split("/")[1:]
    return tuple(t.replace("~1", "/").replace("~0", "~") for t in tokens)


def canonical_pointer(tokens: Tuple[str, ...]) -> str:
    """把 token 序列序列化为规范化指针字符串。"""
    return "".join("/" + t.replace("~", "~0").replace("/", "~1") for t in tokens)


class DocumentStore:
    """按规范化文件 URI 缓存已解析文档；同一文件每次编译最多解析一次。"""

    def __init__(self) -> None:
        self._docs: Dict[str, Any] = {}

    def load(self, file_uri: str) -> Any:
        file_uri = _canonical_file_uri(file_uri)
        if file_uri not in self._docs:
            path = Path(unquote(urlsplit(file_uri).path))
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self._docs[file_uri] = json.load(fh)
            except FileNotFoundError:
                raise RefResolutionError(f"referenced file not found: {file_uri}")
            except json.JSONDecodeError as exc:
                raise RefResolutionError(f"invalid JSON in {file_uri}: {exc}")
        return self._docs[file_uri]

    def resolve_ref(self, base_uri: str, ref: str) -> SourceLocation:
        """把 base_uri 文档中出现的 ref 解析为规范化源位置。"""
        joined = urljoin(base_uri, ref)
        doc_part, fragment = urldefrag(joined)
        file_uri = _canonical_file_uri(doc_part)
        pointer = canonical_pointer(parse_pointer(fragment))
        return SourceLocation(file_uri=file_uri, pointer=pointer)

    def resolve_location(self, location: SourceLocation) -> Any:
        """取出 location 指向的 JSON 值；缺失时抛 RefResolutionError。"""
        doc = self.load(location.file_uri)
        node = doc
        tokens = parse_pointer(location.pointer)
        for token in tokens:
            if isinstance(node, list):
                try:
                    node = node[int(token)]
                except (ValueError, IndexError):
                    raise RefResolutionError(
                        f"unresolvable pointer {location.pointer}: no array index {token}",
                        origin=location,
                    )
            elif isinstance(node, dict):
                if token not in node:
                    raise RefResolutionError(
                        f"unresolvable pointer {location.pointer}: missing key {token!r}",
                        origin=location,
                    )
                node = node[token]
            else:
                raise RefResolutionError(
                    f"unresolvable pointer {location.pointer}: "
                    f"cannot descend into {type(node).__name__}",
                    origin=location,
                )
        return node
