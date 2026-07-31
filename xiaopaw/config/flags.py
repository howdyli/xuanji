"""Feature flags for progressive rollout."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeatureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token_counter_mode: Literal["hf_deepseek", "rough"] = "rough"
    enable_skill_timeout: bool = True
    enable_cron_filelock: bool = True
    enable_memory_save_filelock: bool = True
    enable_feishu_rate_limit_aware: bool = True
    enable_trace_id: bool = True
    enable_mcp_whitelist: bool = True
    enable_memory_save_filter: bool = True
    enable_webhook_replay_cache: bool = True
    enable_inbound_rate_limit: bool = True
    enable_pgvector_rls: bool = False
    enable_pgvector_connection_pool: bool = True
    # P3-1: opt-in planner→executor→reviewer multi-agent collaboration pipeline.
    # Default off; the single-agent orchestrator path is unchanged when disabled.
    enable_multi_agent_collab: bool = False
    # 短期#7：简单问答直答旁路（跳过 Crew 编排，单次 LLM 直调）。
    # 分类器保守（见 agents/direct_answer.py），失败自动回退完整编排。
    enable_direct_answer_bypass: bool = True
    # 远程长期记忆（agent-memory-system SDK 对接）。开启后每轮对话双写
    # 记忆片段到记忆服务，并在推理前召回注入长期记忆上下文。
    # 默认关闭；关闭时行为与现状完全一致（仅 pgvector 索引路径）。
    enable_remote_memory: bool = True
    # Phase 4 FR-5：pgvector 旧索引路径下线开关。双写观察期内保持
    # true（修复后的调度生效）；观察期结束后置 false 切断写入，
    # 一个版本周期无回退诉求后物理删除旧代码。
    enable_pgvector_indexing: bool = True
    # Phase 5：结构化记忆表（Tables）工具。需同时开启
    # enable_remote_memory；默认关闭，灰度验证 AC 后再默认开启。
    enable_structured_tables: bool = True
    # Phase C1：图谱记忆（实体关系抽取与查询）。需同时开启
    # enable_remote_memory；默认关闭。
    enable_graph_memory: bool = True
    # Phase C2：统一双写（本地缓存 + 远程权威源）。需同时开启
    # enable_remote_memory；默认关闭。
    enable_memory_sync: bool = True
    # Phase A：LLM 驱动的结构化记忆抽取。需同时开启
    # enable_remote_memory；默认关闭。
    enable_memory_extraction: bool = True
    # 【已废弃】Phase A 生命周期定时调度已下线：治理（衰减/清理/冲突
    # 检测）上收 agent-memory-system 服务端调度器，本 flag 不再被读取，
    # 仅为兼容旧配置保留。
    enable_memory_lifecycle: bool = True
    # Phase B1：三层分层召回（Profile→语义→实体展开）。需同时开启
    # enable_remote_memory；默认关闭。
    enable_layered_recall: bool = True
    # 图谱查询：召回阶段查询实体关系注入 prompt。需同时开启
    # enable_remote_memory；默认关闭。
    enable_graph_query: bool = True
