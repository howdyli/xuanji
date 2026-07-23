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
