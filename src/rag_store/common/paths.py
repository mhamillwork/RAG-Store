"""Relative path and filename validation.

These checks are the application boundary against path traversal, NUL bytes,
and filenames that cannot be stored safely. Callers still have to confine the
resulting path to a root with ``confine``.
"""

from __future__ import annotations

import re
from pathlib import Path

from rag_store.common.errors import ValidationFailed

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_NAME = 255
_MAX_PATH = 1024


def normalize_relative_path(value: str) -> str:
    if value is None:
        raise ValidationFailed("A relative path is required.")
    text = value.strip().replace("\\", "/")
    if text in {"", "."}:
        return ""
    if text.startswith("/"):
        raise ValidationFailed("Absolute paths are not accepted.")
    parts = text.split("/")
    cleaned: list[str] = []
    for part in parts:
        if part in {"", "."}:
            raise ValidationFailed("Empty path segments are not accepted.")
        if part == "..":
            raise ValidationFailed("Path traversal is not accepted.")
        if _CONTROL.search(part):
            raise ValidationFailed("Control characters are not accepted in paths.")
        if len(part) > _MAX_NAME:
            raise ValidationFailed("A path segment exceeds 255 characters.")
        cleaned.append(part)
    relative = "/".join(cleaned)
    if len(relative) > _MAX_PATH:
        raise ValidationFailed("The relative path is too long.")
    return relative


def validate_filename(name: str) -> str:
    if not name or name.strip() != name:
        raise ValidationFailed("A filename is required.")
    if "/" in name or "\\" in name:
        raise ValidationFailed("A filename cannot contain a path separator.")
    if name in {".", ".."}:
        raise ValidationFailed("The filename is not valid.")
    if _CONTROL.search(name):
        raise ValidationFailed("Control characters are not accepted in filenames.")
    if len(name) > _MAX_NAME:
        raise ValidationFailed("The filename exceeds 255 characters.")
    return name


def parent_path(relative: str) -> str:
    if not relative or "/" not in relative:
        return ""
    return relative.rsplit("/", 1)[0]


def name_of(relative: str) -> str:
    if not relative:
        return ""
    return relative.rsplit("/", 1)[-1]


def join_relative(parent: str, name: str) -> str:
    parent_norm = normalize_relative_path(parent) if parent else ""
    file_name = validate_filename(name) if "/" not in name else normalize_relative_path(name)
    if parent_norm:
        return normalize_relative_path(f"{parent_norm}/{file_name}")
    return normalize_relative_path(file_name) if file_name else ""


def confine(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root`` and reject symlink escapes."""

    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*relative.split("/")) if relative else root_resolved
    if candidate.is_symlink():
        raise ValidationFailed("Symbolic links are not accepted.")
    # Walk existing parents so a symlink in a parent directory is rejected
    # before the final component is created.
    current = root_resolved
    parts = candidate.relative_to(root_resolved).parts
    for part in parts[:-1] if candidate != root_resolved else []:
        current = current / part
        if current.is_symlink():
            raise ValidationFailed("Symbolic links are not accepted.")
        if current.exists() and not current.is_dir():
            raise ValidationFailed("A path segment is not a directory.")
    try:
        candidate.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise ValidationFailed("The path escapes the storage root.") from exc
    return candidate


def storage_key_ok(value: str) -> bool:
    return bool(re.fullmatch(r"user-[0-9a-f]{12}", value or ""))
