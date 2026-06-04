"""SKILL package validator: enforce safety constraints on uploaded skills."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Disallowed file extensions (executable binaries / shared objects)
_BLOCKED_EXTS = {
    ".so", ".dylib", ".dll", ".exe", ".bin",
    ".dmg", ".pkg", ".deb", ".rpm",
}

# Disallowed file names
_BLOCKED_NAMES = {".env", ".git", ".gitignore", ".DS_Store"}

_SAFE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ValidationError(Exception):
    """Raised when skill package validation fails."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def validate_skill_name(name: str) -> None:
    if not name or not _SAFE_NAME_PATTERN.match(name):
        raise ValidationError(
            "invalid_name",
            f"name must be kebab/snake-case, lowercase letters/digits/-/_ (got: {name!r})",
        )


def validate_archive_member(member_name: str) -> str:
    """Validate a single zip entry; return normalized relative posix path.

    Rejects: absolute paths, parent traversal, blocked extensions / names.
    """
    if not member_name or member_name.endswith("/"):
        # Directory entries are tolerated (skipped by callers)
        return member_name
    if member_name.startswith(("/", "\\")):
        raise ValidationError("absolute_path", f"absolute paths not allowed: {member_name}")
    p = PurePosixPath(member_name.replace("\\", "/"))
    parts = p.parts
    if any(part in ("..", "") for part in parts):
        raise ValidationError("path_traversal", f"path traversal blocked: {member_name}")
    # Block dangerous filenames
    if p.name in _BLOCKED_NAMES:
        raise ValidationError("blocked_name", f"file name not allowed: {p.name}")
    if p.suffix.lower() in _BLOCKED_EXTS:
        raise ValidationError("blocked_ext", f"file extension not allowed: {p.suffix}")
    # Hidden files anywhere
    for part in parts:
        if part.startswith(".") and part not in (".", ".."):
            raise ValidationError("hidden_file", f"hidden file not allowed: {member_name}")
    return p.as_posix()


def validate_archive_size(size: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise ValidationError(
            "too_large",
            f"archive too large: {size} > {max_bytes}",
        )


def validate_uncompressed_size(size: int, max_bytes: int) -> None:
    """Total uncompressed size — defends against zip bombs."""
    if size > max_bytes:
        raise ValidationError(
            "uncompressed_too_large",
            f"uncompressed payload too large: {size} > {max_bytes}",
        )
