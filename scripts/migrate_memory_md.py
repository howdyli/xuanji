#!/usr/bin/env python3
"""memory.md 存量偏好一次性迁移脚本（Phase 4 FR-2）。

解析 workspace 内 memory.md「用户重要事项」区的 bullet 条目，
写入 agent-memory-system 的 Variables（POST /memory/variables，
upsert 语义）。key 由条目内容哈希派生（mem_md_<sha8>），重复执行
以 key 覆盖，不产生重复数据（幂等）。

用法：
    python scripts/migrate_memory_md.py --workspace data/workspace --dry-run
    AGENT_MEMORY_URL=http://127.0.0.1:8000/api/v1 \\
    AGENT_MEMORY_API_KEY=amk_xxx \\
    python scripts/migrate_memory_md.py --workspace data/workspace

迁移后 memory.md 保留只读（Bootstrap Prompt 仍加载），双源并存
一个版本周期后再评估移除。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

# 只迁移偏好性质的分区；「待跟进事项/近期对话摘要」属临时状态不迁移
_PREFERENCE_SECTIONS = ("用户重要事项",)

# bullet 条目：- xxx / * xxx / 1. xxx
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+?)\s*$")


def parse_preferences(memory_md: str) -> list[str]:
    """提取偏好分区下的 bullet 条目文本（跳过 > 引导的模板注释）。"""
    entries: list[str] = []
    current_section = ""
    for line in memory_md.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            current_section = heading.group(1)
            continue
        if current_section not in _PREFERENCE_SECTIONS:
            continue
        if line.strip().startswith(">"):
            continue  # 模板注释
        m = _BULLET_RE.match(line)
        if m and m.group(1):
            entries.append(m.group(1))
    return entries


def entry_key(entry: str) -> str:
    """内容哈希派生 key：重复执行同 key 覆盖 → 幂等。"""
    digest = hashlib.sha256(entry.encode("utf-8")).hexdigest()[:8]
    return f"mem_md_{digest}"


def migrate(entries: list[str], base_url: str, api_key: str) -> tuple[int, int]:
    """逐条 upsert 到 Variables。返回 (成功数, 失败数)。"""
    import httpx

    ok = failed = 0
    headers = {"Authorization": f"Bearer {api_key}"}
    for entry in entries:
        try:
            resp = httpx.post(
                f"{base_url.rstrip('/')}/memory/variables",
                json={"key": entry_key(entry), "value": entry, "ttl": None},
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code < 400:
                ok += 1
            else:
                failed += 1
                print(f"  ✗ {entry_key(entry)}: HTTP {resp.status_code} {resp.text[:120]}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {entry_key(entry)}: {exc}")
    return ok, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 memory.md 偏好条目到记忆系统 Variables")
    parser.add_argument("--workspace", required=True, help="workspace 目录（含 memory.md）")
    parser.add_argument("--dry-run", action="store_true", help="只输出将写入的 key/value diff，不实际写入")
    args = parser.parse_args()

    memory_path = Path(args.workspace) / "memory.md"
    if not memory_path.exists():
        print(f"memory.md 不存在：{memory_path}")
        return 1

    entries = parse_preferences(memory_path.read_text(encoding="utf-8"))
    if not entries:
        print(f"未在 {memory_path} 的偏好分区（{'/'.join(_PREFERENCE_SECTIONS)}）中找到可迁移条目。")
        return 0

    print(f"发现 {len(entries)} 条待迁移偏好：")
    for entry in entries:
        print(f"  + {entry_key(entry)} = {entry}")

    if args.dry_run:
        print("\n[dry-run] 未写入。确认无误后去掉 --dry-run 执行迁移。")
        return 0

    base_url = os.environ.get("AGENT_MEMORY_URL", "")
    api_key = os.environ.get("AGENT_MEMORY_API_KEY", "")
    if not base_url or not api_key:
        print("缺少环境变量 AGENT_MEMORY_URL / AGENT_MEMORY_API_KEY")
        return 1

    ok, failed = migrate(entries, base_url, api_key)
    print(f"\n迁移完成：成功 {ok} 条，失败 {failed} 条（重复执行以 key 覆盖，幂等）。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
