"""SkillRegistry —— 扫描内置+用户技能目录，合并元数据并提供 CRUD 能力。

数据流：
  - File system: SKILL.md (frontmatter + body) + scripts/
  - PostgreSQL:  skills 表 (enabled / version / author / source)
  - 启动扫描：以 file system 为真相源，自动 upsert 到 DB
  - 运行查询：DB 优先（含 enabled 状态），DB 不可用时降级文件扫描
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# kebab-case + underscore 都允许（与现有内置技能命名兼容）
_SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

# 含可执行脚本的 task 类技能视为「套件」(bundle)，前端用紫色标签突出。
_SCRIPT_EXTS = (".py", ".sh", ".js", ".ts")


@dataclass
class SkillInfo:
    name: str
    source: str  # 'builtin' | 'user'
    type: str = "task"  # 'task' | 'reference'
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    path: Path | None = None
    files: list[str] = field(default_factory=list)

    @property
    def is_bundle(self) -> bool:
        """True if this is an executable bundle (task + script files)."""
        if self.type != "task":
            return False
        return any(f.endswith(_SCRIPT_EXTS) for f in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "type": self.type,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "enabled": self.enabled,
            "path": str(self.path) if self.path else None,
            "files": self.files,
            "is_bundle": self.is_bundle,
        }


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse SKILL.md frontmatter; return (meta_dict, body)."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
    if not m:
        return {}, content
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        return meta if isinstance(meta, dict) else {}, m.group(2)
    except yaml.YAMLError:
        return {}, content


def _extract_info(skill_dir: Path, source: str) -> SkillInfo | None:
    """Read SKILL.md from a skill directory and build SkillInfo."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("read SKILL.md failed for %s: %s", skill_dir, exc)
        return None

    meta, _body = _parse_frontmatter(content)
    name = str(meta.get("name") or skill_dir.name).strip()
    if not _SKILL_NAME_PATTERN.match(name):
        logger.warning("skill name invalid: %s", name)
        return None

    files: list[str] = []
    for p in skill_dir.rglob("*"):
        if p.is_file():
            try:
                rel = p.relative_to(skill_dir).as_posix()
            except ValueError:
                continue
            files.append(rel)

    return SkillInfo(
        name=name,
        source=source,
        type=str(meta.get("type") or "task"),
        description=str(meta.get("description") or "")[:500],
        author=str(meta.get("author") or ""),
        version=str(meta.get("version") or "1.0.0"),
        enabled=bool(meta.get("enabled", True)),
        path=skill_dir,
        files=sorted(files),
    )


class SkillRegistry:
    """Skill 元数据合并层：file system + DB。"""

    def __init__(
        self,
        builtin_dir: Path,
        user_dir: Path,
        pg_store: Any | None = None,
    ) -> None:
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self._pg = pg_store
        # Load builtin enabled-state from load_skills.yaml as fallback
        self._builtin_manifest = self._load_builtin_manifest()

    def _load_builtin_manifest(self) -> dict:
        manifest_path = self.builtin_dir / "load_skills.yaml"
        if not manifest_path.exists():
            return {}
        try:
            return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}

    # ─── Filesystem scan ─────────────────────────────────────────

    def _scan_dir(self, root: Path, source: str) -> list[SkillInfo]:
        if not root.exists():
            return []
        out: list[SkillInfo] = []
        seen: set[str] = set()
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            info = _extract_info(child, source)
            if not info:
                continue
            if info.name in seen:
                logger.warning("duplicate skill name: %s", info.name)
                continue
            seen.add(info.name)
            # Apply builtin manifest enabled-state if exists
            if source == "builtin" and info.name in self._builtin_manifest:
                cfg = self._builtin_manifest[info.name] or {}
                info.enabled = bool(cfg.get("enabled", True))
                info.type = cfg.get("type", info.type)
            out.append(info)
        return out

    def scan_all(self) -> list[SkillInfo]:
        """Scan both builtin and user dirs. User skills override builtin on conflict."""
        builtins = {s.name: s for s in self._scan_dir(self.builtin_dir, "builtin")}
        users = {s.name: s for s in self._scan_dir(self.user_dir, "user")}
        # User overrides builtin
        merged = {**builtins, **users}
        return list(merged.values())

    # ─── DB sync ─────────────────────────────────────────────────

    def sync_to_db(self) -> int:
        """Upsert filesystem-scanned skills into DB. Returns sync count."""
        if not self._pg or not self._pg._ensure_connection():
            return 0
        skills = self.scan_all()
        try:
            with self._pg._conn.cursor() as cur:
                for s in skills:
                    cur.execute(
                        """INSERT INTO skills (name, source, type, description, author, version, enabled, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                           ON CONFLICT (name) DO UPDATE SET
                               source = EXCLUDED.source,
                               type = EXCLUDED.type,
                               description = EXCLUDED.description,
                               author = EXCLUDED.author,
                               version = EXCLUDED.version,
                               updated_at = NOW()""",
                        (s.name, s.source, s.type, s.description, s.author, s.version, s.enabled),
                    )
            self._pg._conn.commit()
            logger.info("SkillRegistry: synced %d skills to DB", len(skills))
            return len(skills)
        except Exception as exc:
            try:
                self._pg._conn.rollback()
            except Exception:
                pass
            logger.warning("SkillRegistry: sync_to_db failed: %s", exc)
            return 0

    # ─── Query ───────────────────────────────────────────────────

    def list_all(self) -> list[SkillInfo]:
        """List all skills with merged enabled-state from DB if available."""
        skills = self.scan_all()
        if not self._pg or not self._pg._ensure_connection():
            return skills
        # Merge enabled state from DB
        try:
            import psycopg2.extras
            with self._pg._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT name, enabled FROM skills")
                db_state = {row["name"]: row["enabled"] for row in cur.fetchall()}
            for s in skills:
                if s.name in db_state:
                    s.enabled = db_state[s.name]
        except Exception as exc:
            logger.warning("SkillRegistry: list_all DB merge failed: %s", exc)
        return skills

    def get(self, name: str) -> SkillInfo | None:
        for s in self.list_all():
            if s.name == name:
                return s
        return None

    def get_enabled_names(self) -> set[str]:
        return {s.name for s in self.list_all() if s.enabled}

    # ─── Mutations ───────────────────────────────────────────────

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Toggle enable state. DB primary, fallback no-op."""
        if not self._pg or not self._pg._ensure_connection():
            logger.warning("SkillRegistry: DB unavailable, set_enabled is no-op")
            return False
        try:
            with self._pg._conn.cursor() as cur:
                cur.execute(
                    "UPDATE skills SET enabled = %s, updated_at = NOW() WHERE name = %s",
                    (enabled, name),
                )
                affected = cur.rowcount
            self._pg._conn.commit()
            return affected > 0
        except Exception as exc:
            try:
                self._pg._conn.rollback()
            except Exception:
                pass
            logger.warning("SkillRegistry: set_enabled failed: %s", exc)
            return False

    def delete_user_skill(self, name: str) -> tuple[bool, str]:
        """Delete a user skill (filesystem + DB). Builtin skills are protected."""
        info = self.get(name)
        if not info:
            return False, "not_found"
        if info.source != "user":
            return False, "builtin_protected"
        # Remove filesystem
        try:
            import shutil
            target = self.user_dir / name
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
        except OSError as exc:
            logger.warning("SkillRegistry: remove dir failed: %s", exc)
            return False, "fs_error"
        # Remove DB row
        if self._pg and self._pg._ensure_connection():
            try:
                with self._pg._conn.cursor() as cur:
                    cur.execute("DELETE FROM skills WHERE name = %s AND source = 'user'", (name,))
                    cur.execute("DELETE FROM session_skills WHERE skill_name = %s", (name,))
                self._pg._conn.commit()
            except Exception as exc:
                try:
                    self._pg._conn.rollback()
                except Exception:
                    pass
                logger.warning("SkillRegistry: delete DB row failed: %s", exc)
        return True, "ok"

    def write_user_skill(
        self,
        name: str,
        description: str,
        body: str,
        type_: str = "task",
        author: str = "",
        version: str = "1.0.0",
        scripts: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> tuple[bool, str]:
        """Create/update a user skill. Returns (ok, code)."""
        if not _SKILL_NAME_PATTERN.match(name):
            return False, "invalid_name"
        target = self.user_dir / name
        # Conflict with builtin?
        builtin_target = self.builtin_dir / name
        if builtin_target.exists() and not overwrite:
            return False, "builtin_conflict"
        if target.exists() and not overwrite:
            return False, "exists"
        target.mkdir(parents=True, exist_ok=True)
        # Compose SKILL.md
        meta_lines = [
            "---",
            f"name: {name}",
            f"description: {description!r}" if "\n" in description else f"description: {description}",
            f"type: {type_}",
        ]
        if author:
            meta_lines.append(f"author: {author}")
        if version:
            meta_lines.append(f"version: {version}")
        meta_lines.append("---")
        skill_md = "\n".join(meta_lines) + "\n\n" + body.lstrip()
        try:
            (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
            if scripts:
                scripts_dir = target / "scripts"
                scripts_dir.mkdir(exist_ok=True)
                for fname, content in scripts.items():
                    if "/" in fname or ".." in fname:
                        continue
                    (scripts_dir / fname).write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.warning("SkillRegistry: write file failed: %s", exc)
            return False, "fs_error"
        # Sync to DB
        if self._pg and self._pg._ensure_connection():
            try:
                with self._pg._conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO skills (name, source, type, description, author, version, enabled, updated_at)
                           VALUES (%s, 'user', %s, %s, %s, %s, TRUE, NOW())
                           ON CONFLICT (name) DO UPDATE SET
                               type = EXCLUDED.type,
                               description = EXCLUDED.description,
                               author = EXCLUDED.author,
                               version = EXCLUDED.version,
                               updated_at = NOW()""",
                        (name, type_, description[:500], author, version),
                    )
                self._pg._conn.commit()
            except Exception as exc:
                try:
                    self._pg._conn.rollback()
                except Exception:
                    pass
                logger.warning("SkillRegistry: write DB failed: %s", exc)
        return True, "ok"

    # ─── Session bindings ────────────────────────────────────────

    def get_session_skills(self, session_id: str) -> set[str] | None:
        """Get skills enabled for a session. None = use all globally enabled."""
        if not self._pg or not self._pg._ensure_connection():
            return None
        try:
            with self._pg._conn.cursor() as cur:
                cur.execute(
                    "SELECT skill_name FROM session_skills WHERE session_id = %s",
                    (session_id,),
                )
                rows = cur.fetchall()
            if not rows:
                return None
            return {r[0] for r in rows}
        except Exception as exc:
            logger.warning("SkillRegistry: get_session_skills failed: %s", exc)
            return None

    def set_session_skills(self, session_id: str, skill_names: list[str]) -> bool:
        if not self._pg or not self._pg._ensure_connection():
            return False
        try:
            with self._pg._conn.cursor() as cur:
                cur.execute("DELETE FROM session_skills WHERE session_id = %s", (session_id,))
                for name in skill_names:
                    cur.execute(
                        "INSERT INTO session_skills (session_id, skill_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (session_id, name),
                    )
            self._pg._conn.commit()
            return True
        except Exception as exc:
            try:
                self._pg._conn.rollback()
            except Exception:
                pass
            logger.warning("SkillRegistry: set_session_skills failed: %s", exc)
            return False
