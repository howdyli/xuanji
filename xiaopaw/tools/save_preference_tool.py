"""Save user preference tool — persist explicit user preferences to remote memory.

Phase 4 FR-1：用户显式偏好升级为记忆系统 Variables（upsert 语义，
可覆盖更新）。由 orchestrator 模型判断"用户表达了持久偏好"时主动
调用；工具描述中给出正反例约束，避免把闲聊当偏好存。

写入走 remote_memory_store.set_preference_sync（工具跑在 executor
线程，无事件循环）；远程记忆未启用/写入失败均返回提示不抛异常。
"""

from __future__ import annotations

import re
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, field_validator

from xiaopaw.memory.remote_memory import remote_memory_store

# key 规范：小写字母/数字/下划线，如 reply_language、coffee_preference
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class SavePreferenceSchema(BaseModel):
    key: str
    value: str

    @field_validator("key", "value", mode="before")
    @classmethod
    def coerce(cls, v: Any) -> str:
        return v if isinstance(v, str) else str(v)


class SaveUserPreferenceTool(BaseTool):
    name: str = "save_user_preference"
    description: str = (
        "保存用户的持久偏好设置（键值对，重复保存同一 key 会覆盖更新）。"
        "仅当用户明确表达了希望长期生效的偏好时使用。\n"
        "正例（应调用）：\"以后回复我用英文\" → key=reply_language, value=英文；"
        "\"叫我老王\" → key=preferred_name, value=老王；"
        "\"我喜欢喝美式咖啡\" → key=coffee_preference, value=美式咖啡。\n"
        "反例（不要调用）：一次性指令（\"这段翻译成英文\"）、闲聊观点"
        "（\"今天天气不错\"）、临时上下文（\"帮我查下明天航班\"）。\n"
        "key 用小写英文蛇形命名（如 reply_language）；value 为偏好内容原文。"
    )
    args_schema: type = SavePreferenceSchema

    def _run(self, key: str, value: str, **_) -> str:
        key = key.strip().lower()
        if not _KEY_PATTERN.match(key):
            return f"偏好未保存：key '{key}' 不符合小写蛇形命名规范（如 reply_language）。"
        if not value.strip():
            return "偏好未保存：value 不能为空。"
        if not remote_memory_store.is_enabled:
            return "偏好未保存：远程记忆功能未启用。"
        if remote_memory_store.set_preference_sync(key, value.strip()):
            return f"偏好已保存：{key} = {value.strip()}（后续对话将自动生效）。"
        return "偏好保存失败（记忆服务暂不可用），不影响本轮回复。"
