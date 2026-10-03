"""错误类型：编译失败时抛出，包含发起位置与引用链。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SourceLocation:
    """可定位的源位置：规范化的文件 URI + JSON Pointer。"""

    file_uri: str
    pointer: str

    def __str__(self) -> str:  # pragma: no cover - 展示辅助
        return f"{self.file_uri}#{self.pointer}"


@dataclass
class CatalogError(Exception):
    """目录编译失败。message 描述原因，origin 为发起位置，chain 为引用链。"""

    message: str
    origin: Optional[SourceLocation] = None
    chain: List[SourceLocation] = field(default_factory=list)

    def __str__(self) -> str:
        parts = [self.message]
        if self.origin is not None:
            parts.append(f"origin: {self.origin}")
        for i, loc in enumerate(self.chain):
            parts.append(f"  [{i}] {loc}")
        return "\n".join(parts)


class RefResolutionError(CatalogError):
    """引用无法解析（缺失目标 / 纯引用环）。"""
