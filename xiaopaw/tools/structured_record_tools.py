"""Structured record tools — read/write whitelisted memory tables.

Phase 5 FR-3/FR-4：把记忆系统的 Tables 能力以受控工具暴露给
orchestrator 模型。只允许写入配置白名单（memory.structured_tables）
内的表，字段必须是 schema 子集，防止模型随意造 schema。

- SaveStructuredRecordTool：新增记录；record 含 record_id 时转为更新
- QueryStructuredRecordsTool：等值过滤查询（上限 20 条）

写入/查询走 remote_memory_store 的 *_sync 方法（工具跑在 executor
线程，无事件循环）；远程记忆未启用/失败均返回提示文本不抛异常。
"""

from __future__ import annotations

import json
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, field_validator

from xiaopaw.memory.remote_memory import remote_memory_store


def _coerce_dict(v: Any) -> dict:
    """模型可能把 record/filters 传成 JSON 字符串，容错解析。"""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _validate_table_and_fields(table_name: str, fields: set[str]) -> str | None:
    """校验表在白名单内且字段 ⊆ schema。通过返回 None，否则返回错误提示。"""
    schema = remote_memory_store.table_schema(table_name)
    if schema is None:
        allowed = "、".join(remote_memory_store.allowed_tables) or "（无）"
        return f"表 '{table_name}' 不在白名单内，可用表：{allowed}。"
    allowed_fields = {f["name"] for f in schema}
    unknown = fields - allowed_fields
    if unknown:
        return (
            f"字段 {sorted(unknown)} 不在表 '{table_name}' 的 schema 中，"
            f"可用字段：{sorted(allowed_fields)}。"
        )
    return None


class SaveRecordSchema(BaseModel):
    table_name: str
    record: dict

    @field_validator("table_name", mode="before")
    @classmethod
    def coerce_name(cls, v: Any) -> str:
        return v if isinstance(v, str) else str(v)

    @field_validator("record", mode="before")
    @classmethod
    def coerce_record(cls, v: Any) -> dict:
        return _coerce_dict(v)


class SaveStructuredRecordTool(BaseTool):
    name: str = "save_structured_record"
    description: str = (
        "把用户提到的结构化条目保存到记忆表（待办、开销等）。"
        "仅当用户明确提出要记录/添加一条结构化数据时使用。\n"
        "可用表及字段：todo(title, due_date, status)、"
        "expense(item, amount, date)。\n"
        "正例：\"记一下周五要交周报\" → table_name=todo, "
        "record={\"title\": \"交周报\", \"due_date\": \"周五\", \"status\": \"pending\"}；"
        "\"今天午饭花了35块\" → table_name=expense, "
        "record={\"item\": \"午饭\", \"amount\": 35, \"date\": \"今天\"}。\n"
        "反例（不要调用）：闲聊、一次性问题、用户偏好（用 save_user_preference）。\n"
        "更新已有记录：record 中带上 record_id（来自查询结果的 id 字段），"
        "其余字段为要更新的值。"
    )
    args_schema: type = SaveRecordSchema

    def _run(self, table_name: str, record: dict, **_) -> str:
        table_name = table_name.strip().lower()
        # 直接调 _run（不经 args_schema）时也容错 JSON 字符串
        record = _coerce_dict(record)
        record = {k: v for k, v in record.items() if v is not None}
        record_id = record.pop("record_id", record.pop("id", None))
        if not record:
            return "未保存：record 不能为空。"
        err = _validate_table_and_fields(table_name, set(record))
        if err:
            return f"未保存：{err}"
        if not remote_memory_store.is_enabled:
            return "未保存：远程记忆功能未启用。"
        if record_id is not None:
            try:
                rid = int(record_id)
            except (TypeError, ValueError):
                return f"未更新：record_id '{record_id}' 不是有效整数。"
            if remote_memory_store.update_record_sync(table_name, rid, record):
                return f"已更新 {table_name} 表记录 #{rid}：{record}。"
            return "更新失败（记忆服务暂不可用或记录不存在），不影响本轮回复。"
        new_id = remote_memory_store.add_record_sync(table_name, record)
        if new_id is not None:
            return f"已保存到 {table_name} 表（记录 #{new_id}）：{record}。"
        return "保存失败（记忆服务暂不可用），不影响本轮回复。"


class QueryRecordsSchema(BaseModel):
    table_name: str
    filters: dict = {}

    @field_validator("table_name", mode="before")
    @classmethod
    def coerce_name(cls, v: Any) -> str:
        return v if isinstance(v, str) else str(v)

    @field_validator("filters", mode="before")
    @classmethod
    def coerce_filters(cls, v: Any) -> dict:
        return _coerce_dict(v)


class QueryStructuredRecordsTool(BaseTool):
    name: str = "query_structured_records"
    description: str = (
        "查询之前保存的结构化记录（待办、开销等）。"
        "当用户询问自己记录过的条目时使用。\n"
        "可用表：todo(title, due_date, status)、expense(item, amount, date)。\n"
        "正例：\"我还有哪些没做的待办？\" → table_name=todo, "
        "filters={\"status\": \"pending\"}；\"看看我记的所有开销\" → "
        "table_name=expense, filters={}。\n"
        "filters 为字段等值过滤，留空 {} 表示查全部（最多返回 20 条）。"
        "返回结果中的 id 可用于后续更新（save_structured_record 带 record_id）。"
    )
    args_schema: type = QueryRecordsSchema

    def _run(self, table_name: str, filters: dict | None = None, **_) -> str:
        table_name = table_name.strip().lower()
        filters = _coerce_dict(filters) if filters else {}
        filters = {k: v for k, v in filters.items() if v is not None}
        err = _validate_table_and_fields(table_name, set(filters))
        if err:
            return f"查询失败：{err}"
        if not remote_memory_store.is_enabled:
            return "查询失败：远程记忆功能未启用。"
        records = remote_memory_store.query_records_sync(table_name, filters or None)
        if records is None:
            return "查询失败（记忆服务暂不可用），可稍后再试。"
        if not records:
            return f"{table_name} 表中没有匹配的记录。"
        lines = [json.dumps(r, ensure_ascii=False) for r in records[:20]]
        return f"{table_name} 表查询结果（{len(lines)} 条）：\n" + "\n".join(lines)
