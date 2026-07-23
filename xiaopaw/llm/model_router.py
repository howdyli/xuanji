"""ModelRouter —— 多模型路由与负载均衡系统。

【设计目标】
1. 支持多个 AI 模型配置（DeepSeek / Qwen / 其他 OpenAI 兼容）
2. 按任务类型自动选择最优模型（成本/延迟/质量）
3. 内置负载均衡和故障转移机制
4. 统一管理 API Key、超时、重试等配置
5. 零侵入集成现有 AliyunLLM 和 CrewAI

【路由策略】
- task_type: 按 Main Crew / Sub-Crew / Memory Indexer 分配不同模型
- cost_first: 优先使用低成本模型（适合简单任务）
- quality_first: 优先使用高质量模型（适合复杂推理）
- latency_sensitive: 优先使用低延迟模型（适合实时交互）

【故障转移】
- 自动检测模型不可用（HTTP 错误率 > 阈值）
- 自动切换到备用模型
- 支持手动标记模型健康状态

【使用方式】
```python
from xiaopaw.llm.model_router import model_router

# 初始化（从 config.yaml 加载配置）
model_router.init_from_config(config)

# 获取 LLM 实例（自动选择最优模型）
main_llm = model_router.get_llm(task_type="orchestrator")
skill_llm = model_router.get_llm(task_type="skill_execution", skill_name="code_review")

# 手动指定模型
custom_llm = model_router.get_llm(model_name="deepseek-reasoner")

# 查看路由统计
stats = model_router.get_stats()
```
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型枚举，用于自动选择模型。"""

    ORCHESTRATOR = "orchestrator"           # 主任务编排（Main Crew）
    SKILL_EXECUTION = "skill_execution"      # 技能执行（Sub-Crew）
    MEMORY_INDEXING = "memory_indexing"      # 记忆索引/摘要
    CODE_GENERATION = "code_generation"      # 代码生成
    DATA_ANALYSIS = "data_analysis"          # 数据分析
    GENERAL_CHAT = "general_chat"            # 通用对话
    MULTIMODAL = "multimodal"                # 多模态（图片理解）


class RoutingStrategy(str, Enum):
    """路由策略枚举。"""

    COST_FIRST = "cost_first"               # 成本优先（选最便宜的可用模型）
    QUALITY_FIRST = "quality_first"         # 质量优先（选能力最强的模型）
    LATENCY_SENSITIVE = "latency_sensitive"  # 延迟敏感（选响应最快的模型）
    ROUND_ROBIN = "round_robin"              # 轮询均衡（均匀分配请求）
    PRIORITY = "priority"                    # 优先级队列（按配置顺序尝试）
    COMPLEXITY_BASED = "complexity_based"    # 复杂度自适应（按 prompt 复杂度自动选档）


# ── 复杂度自适应路由（P2-3）────────────────────────────
# 关键词命中会显著抬升复杂度评分：复杂推理/代码/架构/多步任务更需要高质量模型。
_COMPLEXITY_KEYWORDS = (
    "分析", "推理", "证明", "设计", "架构", "算法", "优化", "调试", "排查",
    "重构", "方案", "对比", "评估", "规划", "数学", "逐步", "step by step",
    "analyze", "reasoning", "design", "architecture", "algorithm", "optimize",
    "debug", "refactor", "prove", "derive", "strategy",
)

# 复杂度分档阈值（0~1）：≥HIGH 走质量优先，≥MID 走延迟敏感，否则成本优先。
COMPLEXITY_HIGH = 0.66
COMPLEXITY_MID = 0.33


def estimate_prompt_complexity(prompt: str) -> float:
    """根据启发式规则估算 prompt 复杂度，返回 0.0~1.0 的归一化评分。

    评分维度（相加后 clamp 到 [0,1]）：
    - 长度：越长越可能复杂（每 400 字符 +0.15，上限 0.45）
    - 代码块：包含 ``` 代码围栏 +0.25
    - 复杂关键词：命中 _COMPLEXITY_KEYWORDS 每个 +0.12，上限 0.36
    - 多步/多问：出现多个问号或有序列表标记 +0.15

    这是无状态纯函数，便于单测与在路由层复用。
    """
    if not prompt or not prompt.strip():
        return 0.0

    text = prompt
    lowered = text.lower()
    score = 0.0

    # 1. 长度
    score += min(len(text) / 400.0 * 0.15, 0.45)

    # 2. 代码块
    if "```" in text:
        score += 0.25

    # 3. 复杂关键词（去重命中）
    hits = sum(1 for kw in _COMPLEXITY_KEYWORDS if kw in lowered)
    score += min(hits * 0.12, 0.36)

    # 4. 多步 / 多问
    if text.count("?") + text.count("？") >= 2 or re.search(r"(?m)^\s*\d+[.、)]", text):
        score += 0.15

    return max(0.0, min(score, 1.0))


@dataclass
class ModelConfig:
    """单个模型的完整配置。"""

    name: str                               # 模型名称，如 "deepseek-chat"
    display_name: str = ""                  # 显示名称，如 "DeepSeek V3"
    provider: str = "deepseek"             # 提供商：deepseek / qwen / openai 等
    api_key_env: str = "DEEPSEEK_API_KEY"   # API Key 环境变量名
    region: str = "deepseek"                # 区域端点标识
    endpoint_override: str | None = None    # 自定义端点（可选）

    # 能力特征（用于路由决策）
    max_context_tokens: int = 65536         # 最大上下文长度
    supports_function_calling: bool = True  # 支持 function calling
    supports_vision: bool = False            # 支持图片输入
    is_reasoning_model: bool = False        # 是否为思考模型（有 reasoning_content）

    # 性能指标（用于路由排序）
    cost_per_1k_tokens: float = 0.0014      # 输入价格（元/千 token）
    cost_per_1k_output: float = 0.0028     # 输出价格（元/千 token）
    avg_latency_ms: int = 800              # 平均延迟（毫秒，估算值）
    quality_score: float = 7.0             # 质量评分（1-10，越高越好）

    # 运行时约束
    max_rpm: int | None = None             # 每分钟最大请求数（速率限制）
    timeout_s: int = 120                   # 单次请求超时（秒）
    retry_count: int = 2                   # 重试次数

    # 权重（用于轮询）
    weight: int = 100                      # 轮询权重（默认 100）

    # 健康状态
    enabled: bool = True                   # 是否启用
    healthy: bool = True                   # 是否健康（自动更新）

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name


@dataclass
class ModelStats:
    """单个模型的运行时统计信息。"""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    last_call_time: float = 0.0
    consecutive_failures: int = 0          # 连续失败次数
    error_rate: float = 0.0                # 近期错误率（滑动窗口）
    total_input_tokens: int = 0            # 累计输入 token
    total_output_tokens: int = 0           # 累计输出 token
    estimated_cost_usd: float = 0.0        # 累计估算成本（元/按配置单价）

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_calls == 0:
            return 0.0
        return self.total_latency_ms / self.successful_calls

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls


class ModelRouter:
    """多模型路由器核心类（单例）。

    【职责】
    - 维护已注册的模型配置列表
    - 根据 task_type / strategy 选择最优模型
    - 跟踪每个模型的运行时统计和健康状态
    - 执行故障转移逻辑

    【线程安全】
    所有公共方法都是线程安全的（通过实例锁保护）。
    """

    _instance: ModelRouter | None = None

    def __new__(cls) -> ModelRouter:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # ── 核心数据结构 ───────────────────────
        self._models: dict[str, ModelConfig] = {}       # name → ModelConfig
        self._task_routes: dict[TaskType, list[str]] = {}  # TaskType → [model_names]
        self._default_model: str | None = None           # 默认模型名
        self._default_strategy: RoutingStrategy = RoutingStrategy.COST_FIRST
        self._fallback_chain: list[str] = []             # 故障转移链（全局）
        self._stats: dict[str, ModelStats] = {}          # name → ModelStats
        self._round_robin_idx: dict[str, int] = {}       # 轮询计数器

        # ── 配置文件路径（可自定义）──────────────
        self._config_path: Path | None = None

        logger.info("ModelRouter initialized")

    # ════════════════════════════════════════════
    # 公共 API：初始化与配置
    # ════════════════════════════════════════════

    def init_from_config(self, config_dict: dict[str, Any]) -> None:
        """从 config.yaml 的 routing 段初始化路由器。

        示例配置：
        ```yaml
        routing:
          default_model: "deepseek-chat"
          default_strategy: "cost_first"

          models:
            deepseek-chat:
              display_name: "DeepSeek V3 Chat"
              provider: "deepseek"
              cost_per_1k_tokens: 0.0014
              avg_latency_ms: 800
              quality_score: 7.5

            deepseek-reasoner:
              display_name: "DeepSeek R1 Reasoner"
              provider: "deepseek"
              is_reasoning_model: true
              cost_per_1k_tokens: 0.0055
              avg_latency_ms: 5000
              quality_score: 9.0

          task_routes:
            orchestrator: ["deepseek-chat"]
            skill_execution: ["deepseek-chat"]
            memory_indexing: ["deepseek-chat"]
            code_generation: ["deepseek-chat"]
            data_analysis: ["deepseek-chat"]

          fallback_chain: ["deepseek-chat"]
        ```
        """
        routing_cfg = config_dict.get("routing", {})

        # 1. 注册所有模型
        models_cfg = routing_cfg.get("models", {})
        for model_name, model_params in models_cfg.items():
            if isinstance(model_params, dict):
                model_params["name"] = model_name
                self.register_model(ModelConfig(**model_params))

        # 2. 设置默认值
        self._default_model = routing_cfg.get("default_model")
        self._default_strategy = RoutingStrategy(
            routing_cfg.get("default_strategy", "cost_first")
        )

        # 3. 设置任务路由
        task_routes_cfg = routing_cfg.get("task_routes", {})
        for task_type_str, model_list in task_routes_cfg.items():
            try:
                task_type = TaskType(task_type_str)
                self.set_task_route(task_type, model_list)
            except ValueError:
                logger.warning("unknown task_type in routes: %s", task_type_str)

        # 4. 设置故障转移链
        self._fallback_chain = routing_cfg.get("fallback_chain", [])

        logger.info(
            "ModelRouter initialized with %d models, default=%s, strategy=%s",
            len(self._models),
            self._default_model,
            self._default_strategy.value,
        )

    def load_from_file(self, config_path: Path | str) -> None:
        """从 JSON 文件加载额外模型配置（可选）。"""
        path = Path(config_path)
        if not path.exists():
            logger.warning("model routing config file not found: %s", path)
            return

        with path.open("r", encoding="utf-8") as f:
            extra_config = json.load(f)
        self.init_from_config(extra_config)

    # ════════════════════════════════════════════
    # 公共 API：模型注册与管理
    # ════════════════════════════════════════════

    def register_model(self, model_config: ModelConfig) -> None:
        """注册一个新模型或更新已有模型配置。"""
        name = model_config.name
        self._models[name] = model_config

        # 初始化统计数据
        if name not in self._stats:
            self._stats[name] = ModelStats()

        logger.debug("registered model: %s (provider=%s)", name, model_config.provider)

    def unregister_model(self, model_name: str) -> None:
        """移除一个已注册的模型。"""
        if model_name in self._models:
            del self._models[model_name]
            logger.info("unregistered model: %s", model_name)

    def set_task_route(self, task_type: TaskType, model_list: list[str]) -> None:
        """设置某个任务类型的候选模型列表（按优先级排序）。"""
        self._task_routes[task_type] = model_list
        logger.debug(
            "task route set: %s → %s",
            task_type.value,
            model_list,
        )

    def mark_model_unhealthy(self, model_name: str, reason: str = "") -> None:
        """手动将模型标记为不健康（触发故障转移）。"""
        if model_name in self._models:
            self._models[model_name].healthy = False
            logger.warning(
                "model marked unhealthy: %s (reason: %s)",
                model_name,
                reason or "unspecified",
            )

    def mark_model_healthy(self, model_name: str) -> None:
        """恢复模型为健康状态。"""
        if model_name in self._models:
            self._models[model_name].healthy = True
            self._stats[model_name].consecutive_failures = 0
            logger.info("model restored to healthy: %s", model_name)

    def get_available_models(self) -> list[str]:
        """获取当前可用（启用且健康的）模型名列表。"""
        return [
            name
            for name, cfg in self._models.items()
            if cfg.enabled and cfg.healthy
        ]

    # ════════════════════════════════════════════
    # 核心 API：获取 LLM 实例
    # ════════════════════════════════════════════

    def get_llm(
        self,
        *,
        task_type: TaskType | str | None = None,
        skill_name: str | None = None,
        model_name: str | None = None,
        strategy: RoutingStrategy | str | None = None,
        prompt: str | None = None,
    ):
        """根据条件返回最优 AliyunLLM 实例。

        Args:
            task_type: 任务类型，用于查找对应路由规则。
            skill_name: 技能名称（可选），可用于更细粒度的路由。
            model_name: 强制指定模型名（跳过路由）。
            strategy: 本次调用的路由策略（覆盖默认策略）。
            prompt: 本次请求的提示词（可选）；当策略为 complexity_based 时
                用于估算复杂度并自动选档。

        Returns:
            AliyunLLM 实例（已配置好所有参数）。

        Raises:
            ValueError: 无可用模型时抛出。
        """
        # 1. 如果强制指定模型，直接创建
        if model_name:
            cfg = self._resolve_model(model_name)
            return self._create_llm(cfg)

        # 2. 解析参数
        resolved_task = (
            TaskType(task_type) if isinstance(task_type, str) else task_type
        )
        resolved_strategy = (
            RoutingStrategy(strategy)
            if isinstance(strategy, str)
            else (strategy or self._default_strategy)
        )

        # 2.5 复杂度自适应：把 COMPLEXITY_BASED 映射为具体排序策略
        if resolved_strategy == RoutingStrategy.COMPLEXITY_BASED:
            resolved_strategy = self._strategy_for_prompt(prompt)

        # 3. 获取候选列表
        candidates = self._get_candidates(resolved_task, skill_name)
        if not candidates:
            candidates = [self._default_model] if self._default_model else list(self._models.keys())

        # 4. 按策略排序并选择最优
        selected_name = self._select_best(candidates, resolved_strategy)
        selected_cfg = self._resolve_model(selected_name)

        logger.info(
            "route decision: task=%s strategy=%s → model=%s",
            resolved_task.value if resolved_task else "manual",
            resolved_strategy.value,
            selected_name,
        )

        return self._create_llm(selected_cfg)

    def _strategy_for_prompt(self, prompt: str | None) -> RoutingStrategy:
        """根据 prompt 复杂度把 COMPLEXITY_BASED 映射为具体排序策略。

        - 高复杂度 (≥COMPLEXITY_HIGH) → 质量优先（选推理/高质量模型）
        - 中复杂度 (≥COMPLEXITY_MID) → 延迟敏感（兼顾响应速度）
        - 低复杂度 → 成本优先（简单任务用便宜模型）

        prompt 为空时退化为成本优先。
        """
        if not prompt:
            return RoutingStrategy.COST_FIRST
        score = estimate_prompt_complexity(prompt)
        if score >= COMPLEXITY_HIGH:
            chosen = RoutingStrategy.QUALITY_FIRST
        elif score >= COMPLEXITY_MID:
            chosen = RoutingStrategy.LATENCY_SENSITIVE
        else:
            chosen = RoutingStrategy.COST_FIRST
        logger.debug(
            "complexity routing: score=%.2f → strategy=%s", score, chosen.value
        )
        return chosen

    # ════════════════════════════════════════════
    # 内部方法
    # ════════════════════════════════════════════

    def _resolve_model(self, name: str) -> ModelConfig:
        """解析模型名并验证其可用性。如果不可用则走故障转移链。"""
        cfg = self._models.get(name)
        if not cfg:
            raise ValueError(f"model not registered: {name}")

        if not (cfg.enabled and cfg.healthy):
            logger.warning(
                "model %s unavailable (enabled=%s, healthy=%s), trying fallback",
                name,
                cfg.enabled,
                cfg.healthy,
            )
            fallback = self._try_fallback(name)
            if fallback:
                return fallback
            raise RuntimeError(
                f"model {name} unavailable and no fallback configured"
            )

        return cfg

    def _get_candidates(
        self,
        task_type: TaskType | None,
        skill_name: str | None = None,
    ) -> list[str]:
        """获取给定任务的候选模型列表。"""
        if task_type and task_type in self._task_routes:
            base_list = self._task_routes[task_type]
        elif self._default_model:
            base_list = [self._default_model]
        else:
            base_list = []

        # 过滤掉不可用的模型
        available = [
            name
            for name in base_list
            if name in self._models
            and self._models[name].enabled
            and self._models[name].healthy
        ]

        return available

    def _select_best(
        self,
        candidates: list[str],
        strategy: RoutingStrategy,
    ) -> str:
        """根据策略从候选列表中选择最优模型。"""
        if len(candidates) == 1:
            return candidates[0]

        if strategy == RoutingStrategy.COST_FIRST:
            return min(
                candidates,
                key=lambda n: self._models[n].cost_per_1k_tokens,
            )
        elif strategy == RoutingStrategy.QUALITY_FIRST:
            return max(
                candidates,
                key=lambda n: self._models[n].quality_score,
            )
        elif strategy == RoutingStrategy.LATENCY_SENSITIVE:
            return min(
                candidates,
                key=lambda n: self._models[n].avg_latency_ms,
            )
        elif strategy == RoutingStrategy.ROUND_ROBIN:
            idx = self._round_robin_idx.get(strategy.value, 0)
            chosen = candidates[idx % len(candidates)]
            self._round_robin_idx[strategy.value] = idx + 1
            return chosen
        else:  # PRIORITY
            return candidates[0]

    def _try_fallback(self, failed_model: str) -> ModelConfig | None:
        """沿故障转移链查找下一个可用模型。"""
        found_failed = False
        for candidate in self._fallback_chain:
            if candidate == failed_model:
                found_failed = True
                continue
            if found_failed and candidate in self._models:
                cfg = self._models[candidate]
                if cfg.enabled and cfg.healthy:
                    logger.info("fallback activated: %s → %s", failed_model, candidate)
                    return cfg
        return None

    def _create_llm(self, cfg: ModelConfig):  # noqa: ANN201
        """从 ModelConfig 创建 AliyunLLM 实例。"""
        from xiaopaw.llm.aliyun_llm import AliyunLLM

        api_key = os.environ.get(cfg.api_key_env, "")
        return AliyunLLM(
            model=cfg.name,
            region=cfg.region,
            temperature=0.3,
            timeout=cfg.timeout_s,
            retry_count=cfg.retry_count,
            api_key=api_key or None,
        )

    # ════════════════════════════════════════════
    # 统计与监控 API
    # ════════════════════════════════════════════

    def record_call(
        self,
        model_name: str,
        success: bool,
        latency_ms: float,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """记录一次调用结果（由外部调用方报告）。

        input_tokens / output_tokens 为本次调用消耗的 token（可选），
        会按对应 ModelConfig 的单价累计到估算成本。
        """
        stats = self._stats.get(model_name)
        if not stats:
            return

        stats.total_calls += 1
        stats.last_call_time = time.time()

        # 累计 token 与成本（无论成败都记，成本取决于实际消耗）
        if input_tokens or output_tokens:
            stats.total_input_tokens += max(input_tokens, 0)
            stats.total_output_tokens += max(output_tokens, 0)
            cfg = self._models.get(model_name)
            if cfg:
                stats.estimated_cost_usd += (
                    max(input_tokens, 0) * cfg.cost_per_1k_tokens / 1000.0
                    + max(output_tokens, 0) * cfg.cost_per_1k_output / 1000.0
                )

        if success:
            stats.successful_calls += 1
            stats.total_latency_ms += latency_ms
            stats.consecutive_failures = 0
        else:
            stats.failed_calls += 1
            stats.consecutive_failures += 1

            # 自动标记不健康（连续失败 >= N 次）
            threshold = int(os.environ.get("MODEL_UNHEALTHY_THRESHOLD", "5"))
            if stats.consecutive_failures >= threshold:
                self.mark_model_unhealthy(
                    model_name,
                    reason=f"consecutive failures: {stats.consecutive_failures}",
                )

    def get_stats(self) -> dict[str, Any]:
        """获取所有模型的运行时统计快照（含 token/成本汇总）。"""
        result: dict[str, Any] = {
            "total_models": len(self._models),
            "available_models": len(self.get_available_models()),
            "default_model": self._default_model,
            "default_strategy": self._default_strategy.value,
            "models": {},
        }

        agg_calls = 0
        agg_input = 0
        agg_output = 0
        agg_cost = 0.0
        for name, cfg in self._models.items():
            stats = self._stats.get(name, ModelStats())
            result["models"][name] = {
                "display_name": cfg.display_name,
                "provider": cfg.provider,
                "enabled": cfg.enabled,
                "healthy": cfg.healthy,
                "total_calls": stats.total_calls,
                "successful_calls": stats.successful_calls,
                "failed_calls": stats.failed_calls,
                "success_rate": round(stats.success_rate, 4),
                "avg_latency_ms": round(stats.avg_latency_ms, 1),
                "error_rate": round(stats.error_rate, 4),
                "consecutive_failures": stats.consecutive_failures,
                "total_input_tokens": stats.total_input_tokens,
                "total_output_tokens": stats.total_output_tokens,
                "estimated_cost_usd": round(stats.estimated_cost_usd, 6),
            }
            agg_calls += stats.total_calls
            agg_input += stats.total_input_tokens
            agg_output += stats.total_output_tokens
            agg_cost += stats.estimated_cost_usd

        result["totals"] = {
            "total_calls": agg_calls,
            "total_input_tokens": agg_input,
            "total_output_tokens": agg_output,
            "total_tokens": agg_input + agg_output,
            "estimated_cost_usd": round(agg_cost, 6),
        }

        return result

    def reset_stats(self, model_name: str | None = None) -> None:
        """重置统计数据（全部或单个模型）。"""
        if model_name:
            self._stats[model_name] = ModelStats()
        else:
            for name in self._stats:
                self._stats[name] = ModelStats()


# ── 全局单例 ────────────────────────────────────
model_router = ModelRouter()
