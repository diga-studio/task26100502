"""URI and JSON Pointer helpers (no third-party ref resolver)."""

from __future__ import annotations

import os
from urllib.parse import unquote

from dataclasses import dataclass


@dataclass(frozen=True)
class DocKey:
    """Canonical identity of a source document (normalized absolute path)."""

    path: str


@dataclass(frozen=True)
class NodeId:
    """Canonical identity of a schema position: document + JSON Pointer."""

    doc: DocKey
    pointer: str

    def __str__(self) -> str:
        return f"{self.doc.path}#{self.pointer}"


def normalize_doc_path(base_dir: str, ref_path: str) -> str:
    """Resolve a (possibly relative, dot-segmented, %-encoded) file path."""
    decoded = unquote(ref_path)
    if not os.path.isabs(decoded):
        decoded = os.path.join(base_dir, decoded)
    return os.path.abspath(os.path.normpath(decoded))


def split_ref(ref: str) -> "tuple[str, str]":
    """Split a $ref into (file part, fragment part)."""
    if "#" in ref:
        file_part, fragment = ref.split("#", 1)
    else:
        file_part, fragment = ref, ""
    return file_part, fragment


def parse_fragment(fragment: str) -> str:
    """Canonicalize a URI fragment into a JSON Pointer string.

    Percent-decoding is applied first, then ~0/~1 unescaping per segment;
    the result is re-escaped into canonical pointer form.
    """
    decoded = unquote(fragment)
    if decoded == "":
        return ""
    if not decoded.startswith("/"):
        raise ValueError(f"unsupported fragment (not a JSON Pointer): {fragment!r}")
    segments = [pointer_unescape(seg) for seg in decoded.split("/")[1:]]
    pointer = ""
    for seg in segments:
        pointer = join_pointer(pointer, seg)
    return pointer


def pointer_unescape(segment: str) -> str:
    """Decode one JSON Pointer segment (~0/~1 and %-encoding)."""
    segment = unquote(segment)
    return segment.replace("~1", "/").replace("~0", "~")


def pointer_escape(segment: str) -> str:
    """Encode one JSON Pointer segment."""
    return segment.replace("~", "~0").replace("/", "~1")


def join_pointer(base: str, segment: str) -> str:
    """Append an escaped segment to a JSON Pointer."""
    return base + "/" + pointer_escape(segment)


def resolve_pointer(doc: object, pointer: str) -> object:
    """Evaluate a JSON Pointer against a decoded JSON document."""
    if pointer == "":
        return doc
    current = doc
    for raw in pointer.split("/")[1:]:
        segment = pointer_unescape(raw)
        if isinstance(current, dict):
            if segment not in current:
                raise KeyError(segment)
            current = current[segment]
        elif isinstance(current, list):
            index = int(segment)  # raises ValueError on non-numeric token
            current = current[index]  # raises IndexError out of range
        else:
            raise KeyError(segment)
    return current
