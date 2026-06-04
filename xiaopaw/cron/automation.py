"""AutomationRegistry: business logic + preset templates for scheduled tasks."""

from __future__ import annotations

import logging
from pathlib import Path

from xiaopaw.cron.storage import CronStorage

logger = logging.getLogger(__name__)

# ── preset templates ────────────────────────────────────────────────────────

TEMPLATES: list[dict] = [
    {
        "name": "daily_summary",
        "display_name": "每日工作总结",
        "description": "每个工作日傍晚自动总结当天工作内容，生成结构化报告。",
        "icon": "📝",
        "cron_expr": "0 18 * * 1-5",
        "cron_hint": "周一至周五 18:00",
        "action_type": "dispatch",
        "skill_name": "",
        "content": "请总结今天的工作内容，包括：1) 已完成的任务 2) 遇到的问题及解决方案 3) 明日计划。以结构化格式输出。",
    },
    {
        "name": "morning_brief",
        "display_name": "晨会简报",
        "description": "每个工作日早晨自动生成团队简报，回顾昨日进展和今日重点。",
        "icon": "🌅",
        "cron_expr": "0 9 * * 1-5",
        "cron_hint": "周一至周五 09:00",
        "action_type": "dispatch",
        "skill_name": "",
        "content": "生成今日晨会简报：1) 昨日工作回顾 2) 今日重点任务 3) 需要协调的事项。",
    },
    {
        "name": "scheduled_search",
        "display_name": "定时信息检索",
        "description": "每天定时使用搜索引擎检索指定主题的最新信息并整理报告。",
        "icon": "🔍",
        "cron_expr": "0 10 * * *",
        "cron_hint": "每天 10:00",
        "action_type": "skill",
        "skill_name": "baidu_search",
        "content": "搜索今日行业热点新闻和技术动态，整理为简报格式，包含标题、摘要和链接。",
    },
    {
        "name": "weekly_report",
        "display_name": "周报生成",
        "description": "每周五下午自动生成周报文档，汇总本周工作成果。",
        "icon": "📊",
        "cron_expr": "0 17 * * 5",
        "cron_hint": "每周五 17:00",
        "action_type": "skill",
        "skill_name": "docx",
        "content": "生成本周工作周报，包含：1) 本周完成的主要工作 2) 关键成果 3) 遇到的挑战 4) 下周计划。输出为 Word 文档。",
    },
    {
        "name": "data_monitor",
        "display_name": "数据监控报告",
        "description": "每4小时自动检查并汇报关键数据指标变化情况。",
        "icon": "📈",
        "cron_expr": "0 */4 * * *",
        "cron_hint": "每4小时",
        "action_type": "dispatch",
        "skill_name": "",
        "content": "检查并汇报当前关键数据指标的变化情况，如有异常请重点标注并给出初步分析。",
    },
    {
        "name": "code_review",
        "display_name": "代码审查提醒",
        "description": "每周一上午提醒进行代码审查，检查待处理的 PR 和代码质量。",
        "icon": "🔧",
        "cron_expr": "0 10 * * 1",
        "cron_hint": "每周一 10:00",
        "action_type": "dispatch",
        "skill_name": "",
        "content": "提醒进行本周代码审查：1) 检查待处理的代码 PR 2) 回顾上周代码质量问题 3) 提出改进建议。",
    },
]

_TEMPLATE_MAP: dict[str, dict] = {t["name"]: t for t in TEMPLATES}


class AutomationRegistry:
    """Business logic layer wrapping CronStorage with template support."""

    def __init__(self, db_path: Path, *, data_dir: Path | None = None) -> None:
        self._storage = CronStorage(db_path=db_path, data_dir=data_dir)

    # ── task CRUD ───────────────────────────────────────────────────────

    def list_tasks(self) -> list[dict]:
        jobs = self._storage.load_all()
        return [j.model_dump() for j in jobs]

    def get_task(self, task_id: str) -> dict | None:
        return self._storage.get(task_id)

    def create_task(self, data: dict) -> dict:
        if not data.get("cron_expr"):
            raise ValueError("cron_expr is required")
        if not data.get("name") and not data.get("content"):
            raise ValueError("name or content is required")
        result = self._storage.create(data)
        logger.info("automation: created task %s (%s)", result.get("id"), result.get("name"))
        return result

    def update_task(self, task_id: str, data: dict) -> dict | None:
        result = self._storage.update(task_id, data)
        if result:
            logger.info("automation: updated task %s", task_id)
        return result

    def delete_task(self, task_id: str) -> bool:
        ok = self._storage.delete(task_id)
        if ok:
            logger.info("automation: deleted task %s", task_id)
        return ok

    def toggle_task(self, task_id: str) -> dict | None:
        result = self._storage.toggle(task_id)
        if result:
            logger.info("automation: toggled task %s → enabled=%s", task_id, result.get("enabled"))
        return result

    # ── templates ───────────────────────────────────────────────────────

    def list_templates(self) -> list[dict]:
        return TEMPLATES

    def create_from_template(self, template_name: str, overrides: dict | None = None) -> dict:
        tmpl = _TEMPLATE_MAP.get(template_name)
        if not tmpl:
            raise ValueError(f"template not found: {template_name}")
        data = {
            "name": tmpl["display_name"],
            "description": tmpl["description"],
            "cron_expr": tmpl["cron_expr"],
            "action_type": tmpl["action_type"],
            "skill_name": tmpl["skill_name"],
            "content": tmpl["content"],
        }
        if overrides:
            for k in ("name", "description", "cron_expr", "action_type", "skill_name", "content"):
                if k in overrides and overrides[k] is not None:
                    data[k] = overrides[k]
        return self.create_task(data)

    # ── internal access for CronService ─────────────────────────────────

    @property
    def storage(self) -> CronStorage:
        return self._storage
