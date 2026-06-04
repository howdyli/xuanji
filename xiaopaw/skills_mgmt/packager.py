"""Skill ZIP packager: pack a skill dir into .zip and unpack uploaded .zip safely."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import yaml

from xiaopaw.skills_mgmt.validator import (
    ValidationError,
    validate_archive_member,
    validate_archive_size,
    validate_skill_name,
    validate_uncompressed_size,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ARCHIVE_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024  # 20 MB
DEFAULT_MAX_FILES = 200


def pack_skill(skill_dir: Path) -> bytes:
    """Pack a skill directory into a .zip blob (in-memory)."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise FileNotFoundError(f"skill dir not found: {skill_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(skill_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(skill_dir).as_posix()
            # Skip hidden files / __pycache__
            if any(part.startswith(".") or part == "__pycache__" for part in rel.split("/")):
                continue
            zf.writestr(rel, p.read_bytes())
    return buf.getvalue()


def unpack_skill(
    archive_bytes: bytes,
    target_root: Path,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    overwrite: bool = False,
) -> tuple[str, Path]:
    """Unpack a .zip into target_root/<skill_name>/.

    Returns (skill_name, target_dir).
    Raises ValidationError on any safety check failure.
    The skill name is read from SKILL.md frontmatter (required).
    """
    validate_archive_size(len(archive_bytes), max_archive_bytes)

    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ValidationError("bad_zip", str(exc))

    # Pre-scan: total uncompressed size + file count + locate SKILL.md
    members = zf.infolist()
    if len(members) > max_files:
        raise ValidationError("too_many_files", f"file count {len(members)} > {max_files}")

    total_uncompressed = sum(m.file_size for m in members)
    validate_uncompressed_size(total_uncompressed, max_uncompressed_bytes)

    # Find SKILL.md (could be at root or under a single top-level dir)
    skill_md_member = None
    top_level_prefix = ""

    for m in members:
        if m.is_dir():
            continue
        try:
            normalized = validate_archive_member(m.filename)
        except ValidationError:
            raise
        parts = normalized.split("/")
        if parts[-1] == "SKILL.md":
            if len(parts) == 1:
                skill_md_member = m
                top_level_prefix = ""
                break
            elif len(parts) == 2:
                # File under a single top-level directory
                skill_md_member = m
                top_level_prefix = parts[0] + "/"
                break

    if skill_md_member is None:
        raise ValidationError("missing_skill_md", "SKILL.md not found at archive root or first level")

    # Parse SKILL.md to determine target name
    skill_md_content = zf.read(skill_md_member).decode("utf-8", errors="replace")
    name = _read_name_from_skill_md(skill_md_content)
    if not name:
        raise ValidationError("missing_skill_name", "SKILL.md frontmatter must define 'name'")
    validate_skill_name(name)

    target_dir = target_root / name
    if target_dir.exists() and not overwrite:
        raise ValidationError("exists", f"skill already exists: {name}")

    # Clean target if overwrite
    if target_dir.exists() and overwrite:
        import shutil
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Extract files
    for m in members:
        if m.is_dir():
            continue
        normalized = validate_archive_member(m.filename)
        # Strip top-level dir prefix if present
        if top_level_prefix and normalized.startswith(top_level_prefix):
            rel = normalized[len(top_level_prefix):]
        elif top_level_prefix and not normalized.startswith(top_level_prefix):
            # file outside the named dir — skip silently
            continue
        else:
            rel = normalized
        if not rel:
            continue
        # Per-file size sanity
        if m.file_size > max_uncompressed_bytes:
            raise ValidationError("file_too_large", f"file too large: {rel}")
        out_path = target_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Use stream copy to avoid double allocation
        with zf.open(m) as src, out_path.open("wb") as dst:
            written = 0
            while True:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_uncompressed_bytes:
                    raise ValidationError("payload_overflow", "uncompressed overflow during extract")
                dst.write(chunk)

    return name, target_dir


def _read_name_from_skill_md(content: str) -> str:
    """Extract `name` from SKILL.md frontmatter. Returns '' if missing."""
    import re
    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return ""
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            return ""
        return str(meta.get("name") or "").strip()
    except yaml.YAMLError:
        return ""
