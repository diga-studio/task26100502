"""Error types for catalog compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class SourceLocation:
    """A position inside a source document."""

    file: str
    pointer: str

    def __str__(self) -> str:
        return f"{self.file}#{self.pointer}"


@dataclass
class RefChainEntry:
    """One hop of a $ref chain: where the $ref appears and what it targets."""

    at: SourceLocation
    ref: str


class CatalogError(Exception):
    """Base error for catalog compilation failures."""


class RefResolutionError(CatalogError):
    """A $ref could not be resolved (missing target or pure ref cycle)."""

    def __init__(
        self,
        message: str,
        origin: SourceLocation,
        chain: List[RefChainEntry] = (),
    ) -> None:
        self.origin = origin
        self.chain = list(chain)
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        lines = [f"{message} (origin: {self.origin})"]
        for entry in self.chain:
            lines.append(f"  at {entry.at} -> $ref {entry.ref!r}")
        return "\n".join(lines)
