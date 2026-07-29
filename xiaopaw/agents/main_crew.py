"""MemoryAwareCrew: main agent with three-layer memory and hook integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yaml
from crewai import Agent, Crew, Process, Task
from crewai.agents.parser import AgentAction, AgentFinish
from crewai.hooks import (
    LLMCallHookContext,
    ToolCallHookContext,
    before_llm_call,
    before_tool_call,
    unregister_before_tool_call_hook,
)
from crewai.project import CrewBase, agent, crew, task

from xiaopaw.hook_framework.crew_adapter import get_current_adapter

from xiaopaw.agents.models import MainTaskOutput
from xiaopaw.config.flags import FeatureFlags
from xiaopaw.llm.model_router import model_router  # ✅ P2-1: 多模型路由器
from xiaopaw.memory.bootstrap import build_bootstrap_prompt
from xiaopaw.memory.context_mgmt import (
    append_session_raw_async,
    load_session_ctx,
    maybe_compress,
    prune_tool_results,
    save_session_ctx_async,
)
from xiaopaw.memory.indexer import async_index_turn, _classify_fragment_type
from xiaopaw.memory.remote_memory import remote_memory_store
from xiaopaw.models import SenderProtocol
from xiaopaw.session.models import MessageEntry
from xiaopaw.tools.intermediate_tool import IntermediateTool
from xiaopaw.tools.knowledge_search_tool import KnowledgeSearchTool

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent / "config"
_DEFAULT_MAX_HISTORY_TURNS = 20

AgentFn = Callable[
    [str, list[MessageEntry], str, str, bool],
    Awaitable[tuple[str, list[str]]],
]


_MCP_TOOL_PREFIXES = ("sandbox_", "mcp_")

_PY_NONE_STRINGS = {"None"}
_PY_TRUE_STRINGS = {"True"}
_PY_FALSE_STRINGS = {"False"}


def _is_mcp_sandbox_tool(tool_name: str) -> bool:
    return any(tool_name.startswith(p) for p in _MCP_TOOL_PREFIXES)


def _normalize_tool_input(tool_input: dict) -> None:
    """MCP sandbox tool parameter normalization. Fixes Python-style type errors only."""
    for key in list(tool_input.keys()):
        val = tool_input[key]
        if not isinstance(val, str):
            continue
        if val in _PY_NONE_STRINGS:
            del tool_input[key]
        elif val in _PY_TRUE_STRINGS:
            tool_input[key] = True
        elif val in _PY_FALSE_STRINGS:
            tool_input[key] = False


# Canonical role label for the executor agent. Any direct/unknown LLM call also
# maps here, so the single-agent path and its observability traces are unchanged.
_EXECUTOR_ROLE_LABEL = "orchestrator"


def _build_role_label_map(agents_cfg: dict[str, Any]) -> dict[str, str]:
    """Map each agent's configured ``role`` string → its canonical yaml key.

    e.g. ``{"xuanji 工作助手": "orchestrator", "任务规划专家": "planner", ...}``.
    Templated roles (skill_agent's ``"{skill_name_upper} ..."``) are skipped —
    they belong to a different crew and are resolved per-skill.
    """
    out: dict[str, str] = {}
    for key, spec in agents_cfg.items():
        role = spec.get("role") if isinstance(spec, dict) else None
        if isinstance(role, str) and "{" not in role:
            out[role.strip()] = key
    return out


def _resolve_agent_role_label(
    agent: Any, role_map: dict[str, str], default: str = _EXECUTOR_ROLE_LABEL
) -> str:
    """Resolve the executing agent's canonical role label for observability.

    Falls back to ``default`` ("orchestrator") for direct/unknown LLM calls so the
    single-agent path stays labeled exactly as before.
    """
    role_str = getattr(agent, "role", "") if agent is not None else ""
    if not role_str:
        return default
    return role_map.get(str(role_str).strip(), default)


def _make_step_callback(
    sender: SenderProtocol, routing_key: str
) -> Callable[[Any], Awaitable[None]]:
    """生成 CrewAI step_callback —— 每个推理 step 后触发。

    【L33 接线点：pending_deny 的安全出口】
    BEFORE_TOOL_CALL 抛的 GuardrailDeny 会被 CrewAI 吞掉（视为工具失败重试），
    所以 adapter 把 deny 存入 _pending_deny 字段。本回调是它的"重抛出口"——
    在 step 结束时把 deny 抛出，CrewAI 才会真正终止执行。

    【dispatch_after_turn 的作用】
    触发 AFTER_TURN 事件链：cost_guard 算账、loop_detector 检测循环、
    langfuse_trace 关闭本轮 generation。
    """
    async def _callback(step_output: Any) -> None:
        # Don't call send_thinking here: it creates orphaned cards.
        # The runner's card (sent before agent_fn) already shows thinking state.

        adapter = get_current_adapter()
        if not adapter:
            return

        # 提取本 step 的输出文本，喂给 AFTER_TURN（loop_detector 用它判循环）
        step_text = ""
        if isinstance(step_output, AgentAction):
            step_text = str(step_output.text or step_output.thought or "")
        elif isinstance(step_output, AgentFinish):
            step_text = str(getattr(step_output, "output", "") or "")
        adapter.dispatch_after_turn(output=step_text[:2000])

        # ★ pending_deny 重抛口 —— 让 BEFORE_TOOL_CALL 拦截到的 deny 真正生效
        if adapter._pending_deny:
            pending = adapter._pending_deny
            adapter._pending_deny = None
            raise pending

    return _callback


@CrewBase
class MemoryAwareCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        session_id: str,
        routing_key: str,
        user_message: str,
        sender: SenderProtocol,
        workspace_dir: Path,
        ctx_dir: Path,
        history_all: list[MessageEntry],
        db_dsn: str = "",
        max_history_turns: int = _DEFAULT_MAX_HISTORY_TURNS,
        sandbox_url: str = "",
        flags: FeatureFlags | None = None,
        skill_registry: Any | None = None,
        user_skills_dir: Path | None = None,
        recalled_memory: str = "",
        user_preferences: dict | None = None,
        verbose: bool = False,
    ) -> None:
        self.session_id = session_id
        self.routing_key = routing_key
        self.user_message = user_message
        self._sender = sender
        self._workspace_dir = workspace_dir
        self._ctx_dir = ctx_dir
        self._db_dsn = db_dsn
        self._history_all = history_all
        self._max_history_turns = max_history_turns
        self._sandbox_url = sandbox_url
        self._flags = flags or FeatureFlags()
        self._skill_registry = skill_registry
        self._user_skills_dir = user_skills_dir
        self._recalled_memory = recalled_memory
        self._user_preferences = user_preferences or {}
        self._verbose = verbose

        self._step_callback = _make_step_callback(sender, routing_key)
        self._prune_keep_turns = 10
        self._session_loaded = False
        self._last_msgs: list[dict] = []
        self._history_len = 0
        self._turn_start_ts = int(time.time() * 1000)

        self._index_tasks: set[asyncio.Task] = set()
        self._role_label_map_cache: dict[str, str] | None = None

    @agent
    def orchestrator(self) -> Agent:
        agents_cfg = yaml.safe_load(
            (_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8")
        )
        cfg = agents_cfg["orchestrator"]
        cfg["backstory"] = build_bootstrap_prompt(self._workspace_dir)
        # 远程长期记忆召回注入：拼在 bootstrap prompt 之后（空召回零污染）
        if self._recalled_memory:
            cfg["backstory"] += (
                "\n\n<long_term_memory>\n"
                "以下为长期记忆召回内容，供参考，可能过时：\n"
                f"{self._recalled_memory}\n"
                "</long_term_memory>"
            )
        # Phase 4 FR-1：已存用户偏好键值注入（上限 20 条在读取侧控制）
        if self._user_preferences:
            pref_lines = "\n".join(
                f"- {k}: {v}" for k, v in self._user_preferences.items()
            )
            cfg["backstory"] += (
                "\n\n<user_preferences>\n"
                "用户已保存的持久偏好（回复时应遵循）：\n"
                f"{pref_lines}\n"
                "</user_preferences>"
            )

        from xiaopaw.tools.skill_loader import SkillLoaderTool

        # Resolve per-session enabled-skills subset from registry (DB-backed)
        enabled_skills: set | None = None
        if self._skill_registry is not None:
            try:
                enabled_skills = self._skill_registry.get_session_skills(self.session_id)
            except Exception as exc:
                logger.warning("main_crew: get_session_skills failed: %s", exc)
                enabled_skills = None

        skill_tool = SkillLoaderTool(
            session_id=self.session_id,
            sandbox_url=self._sandbox_url,
            routing_key=self.routing_key,
            history_all=self._history_all,
            enabled_skills=enabled_skills,
            user_skills_dir=self._user_skills_dir,
        )

        # Knowledge-base retrieval over the caller's personal libraries. Tenant
        # context is bound here (never from the LLM); a missing DSN yields a
        # tool that reports "not configured" rather than raising. Session-bound
        # bases (session_knowledge_bases) restrict retrieval to the bound set;
        # lookup failures degrade to unrestricted retrieval, never block the turn.
        allowed_kb_ids: list[str] | None = None
        if self._db_dsn:
            try:
                from xiaopaw.knowledge.store import KnowledgeStore

                bound = KnowledgeStore(self._db_dsn).get_session_bases(self.session_id)
                allowed_kb_ids = bound or None
            except Exception as exc:
                logger.warning("main_crew: get_session_bases failed: %s", exc)
                allowed_kb_ids = None

        knowledge_tool = KnowledgeSearchTool(
            routing_key=self.routing_key,
            db_dsn=self._db_dsn,
            allowed_kb_ids=allowed_kb_ids,
        )
        if allowed_kb_ids:
            knowledge_tool.description += (
                f"（当前会话已绑定 {len(allowed_kb_ids)} 个知识库，检索将限定在绑定范围内。）"
            )

        tools = [skill_tool, IntermediateTool(), knowledge_tool]
        # Phase 4 FR-1：远程记忆启用时才挂载偏好保存工具（避免模型
        # 在功能关闭时调用得到"未启用"废回答）
        if getattr(self._flags, "enable_remote_memory", False):
            from xiaopaw.tools.save_preference_tool import SaveUserPreferenceTool

            tools.append(SaveUserPreferenceTool())

            # Phase 5 FR-3/FR-4：结构化记忆表工具（双 flag 门控灰度）
            if getattr(self._flags, "enable_structured_tables", False):
                from xiaopaw.tools.structured_record_tools import (
                    QueryStructuredRecordsTool,
                    SaveStructuredRecordTool,
                )

                tools.append(SaveStructuredRecordTool())
                tools.append(QueryStructuredRecordsTool())

        return Agent(
            **cfg,
            tools=tools,
            # ✅ P2-1: 使用 ModelRouter 自动选择最优模型（支持多模型路由）
            llm=model_router.get_llm(task_type="orchestrator"),
            verbose=self._verbose,
        )

    @task
    def main_task(self) -> Task:
        tasks_cfg = yaml.safe_load(
            (_CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8")
        )
        return Task(
            **tasks_cfg["main_task"],
            agent=self.orchestrator(),
            output_pydantic=MainTaskOutput,
        )

    @before_tool_call
    def before_tool_hook(self, context: ToolCallHookContext) -> bool | None:
        adapter = get_current_adapter()
        if adapter:
            adapter.on_before_tool_call(
                tool_name=context.tool_name,
                tool_input=dict(context.tool_input),
            )
            if _is_mcp_sandbox_tool(context.tool_name):
                _normalize_tool_input(context.tool_input)
        return None

    @crew
    def crew(self) -> Crew:
        # ★ L33 接线点：把 adapter 的两个 callback 装进 CrewAI Crew
        # step_callback：每个推理 step 触发 → AFTER_TURN + pending_deny 重抛
        # task_callback：Task 完成时触发 → TASK_COMPLETE + pending_deny 重抛（最后一道防线）
        # 这是 33 课课文里"+2 处接线"的具体落点。
        adapter = get_current_adapter()
        task_cb = adapter.make_task_callback() if adapter else None

        # P3-1: opt-in planner→executor→reviewer pipeline. Default off keeps the
        # single-agent path (self.agents / self.tasks) exactly as before.
        if getattr(self._flags, "enable_multi_agent_collab", False):
            from xiaopaw.agents.collab_crew import build_collab_crew

            agents_cfg = yaml.safe_load(
                (_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8")
            )
            tasks_cfg = yaml.safe_load(
                (_CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8")
            )
            return build_collab_crew(
                executor_agent=self.orchestrator(),
                main_task=self.main_task(),
                llm_factory=model_router.get_llm,
                agents_cfg=agents_cfg,
                tasks_cfg=tasks_cfg,
                output_pydantic=MainTaskOutput,
                step_callback=self._step_callback,
                task_callback=task_cb,
                verbose=self._verbose,
            )

        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=self._verbose,
            step_callback=self._step_callback,
            task_callback=task_cb,
        )

    def _role_label_map(self) -> dict[str, str]:
        """Lazily build & cache role-string → canonical-label map from agents.yaml."""
        if self._role_label_map_cache is None:
            agents_cfg = yaml.safe_load(
                (_CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8")
            )
            self._role_label_map_cache = _build_role_label_map(agents_cfg)
        return self._role_label_map_cache

    @before_llm_call
    def before_llm_hook(self, context: LLMCallHookContext) -> bool | None:
        # Which agent is calling? Single-agent mode is always the orchestrator;
        # the collab pipeline adds planner/reviewer, whose LLM calls must be
        # attributed correctly — langfuse/audit/EventBus all key off this label.
        role_label = _resolve_agent_role_label(
            getattr(context, "agent", None), self._role_label_map()
        )

        # Session restore, context prune/compress and index bookkeeping belong to
        # the EXECUTOR (orchestrator), which owns the persisted conversation. The
        # planner/reviewer are ephemeral per-turn reasoners; in collab mode the
        # planner is the FIRST LLM call, so restoring history into it (and setting
        # _session_loaded) would starve the executor. Gate all of it on the
        # executor role — this is a no-op change for the single-agent path.
        if role_label == _EXECUTOR_ROLE_LABEL:
            if not self._session_loaded:
                self._restore_session(context)
                self._session_loaded = True
            self._last_msgs = context.messages
            len_before = len(context.messages)
            prune_tool_results(context.messages, keep_turns=self._prune_keep_turns)
            maybe_compress(
                context.messages,
                model_limit=self._flags.context_window_tokens
                if hasattr(self._flags, "context_window_tokens")
                else 32000,
            )
            len_after = len(context.messages)
            if len_after < len_before:
                self._history_len = max(0, self._history_len - (len_before - len_after))

        adapter = get_current_adapter()
        if adapter:
            llm_model = ""
            if context.llm:
                llm_model = getattr(context.llm, "model", "") or ""
                if isinstance(llm_model, str) and "/" in llm_model:
                    llm_model = llm_model.rsplit("/", 1)[-1]
            adapter.on_before_llm(
                agent_role=role_label,
                messages=context.messages,
                model=llm_model,
            )

        return None

    def _restore_session(self, context: LLMCallHookContext) -> None:
        history = load_session_ctx(self.session_id, ctx_dir=self._ctx_dir)
        if not history:
            return
        current_system_msgs = [m for m in context.messages if m.get("role") == "system"]
        current_user_msg = None
        for m in reversed(context.messages):
            if m.get("role") == "user":
                current_user_msg = m
                break

        hist_conv = [
            m for m in history
            if m.get("role") != "system"
            or "<context_summary>" in str(m.get("content", ""))
        ]

        self._history_len = len(current_system_msgs) + len(hist_conv)
        context.messages.clear()
        context.messages.extend(current_system_msgs)
        context.messages.extend(hist_conv)
        if current_user_msg:
            context.messages.append(current_user_msg)

    async def run_and_index(self) -> tuple[str, list[str]]:
        try:
            max_retries = 2
            _last_exc: Exception | None = None

            for attempt in range(max_retries):
                try:
                    result = await self.crew().akickoff(
                        inputs={"user_message": self.user_message}
                    )
                    break  # success
                except Exception as exc:
                    _last_exc = exc
                    exc_str = str(exc)
                    # Retry on transient CrewAI storage/DB errors
                    if "Database initialization error" in exc_str or "unable to open database file" in exc_str:
                        if attempt < max_retries - 1:
                            logger.warning(
                                "CrewAI DB error (attempt %d/%d), retrying: %s",
                                attempt + 1, max_retries, exc_str,
                            )
                            # Clean stale WAL/SHM files that may block SQLite
                            self._cleanup_crewai_db_locks()
                            await asyncio.sleep(1.0)
                            continue
                    raise  # non-retryable or exhausted retries

            new_msgs = self._last_msgs[self._history_len:] if self._last_msgs else []
            # Non-blocking file I/O: run_and_index runs on the event loop, so use
            # the async (asyncio.to_thread) variants to avoid stalling other
            # concurrent sessions on disk writes.
            await append_session_raw_async(self.session_id, new_msgs, self._ctx_dir)
            await save_session_ctx_async(self.session_id, list(self._last_msgs), self._ctx_dir)

            used_skills: list[str] = []
            try:
                reply = result.pydantic.reply if result.pydantic else result.raw
                if result.pydantic and hasattr(result.pydantic, "used_skills"):
                    used_skills = list(result.pydantic.used_skills or [])
            except Exception:
                reply = str(result.raw) if result.raw else str(result)

            # Phase C2：统一双写生效时本地写入由 write_through 负责，
            # 跳过独立索引任务，避免并发双写抢先落库后吞掉 pending_sync 标记
            memory_sync_active = (
                getattr(self._flags, "enable_remote_memory", False)
                and getattr(self._flags, "enable_memory_sync", False)
            )
            # P3: 提前计算 fragment_type，供 pgvector 索引和远程记忆双写共用
            _conv_msgs = [
                {"role": "user", "content": self.user_message},
                {"role": "assistant", "content": reply},
            ]
            _frag_type = _classify_fragment_type(_conv_msgs)
            if (
                self._db_dsn
                and getattr(self._flags, "enable_pgvector_indexing", True)
                and not memory_sync_active
            ):
                # Phase 4 FR-5：修复存量 bug —— 旧代码把 coroutine 赋给
                # self._index_coroutine 但从未调度（never awaited），pgvector
                # 写入实际从未执行。现改为 create_task 真正后台运行，并受
                # enable_pgvector_indexing 开关控制（双写观察期后置 false 下线）。
                index_task = asyncio.get_running_loop().create_task(
                    async_index_turn(
                        session_id=self.session_id,
                        routing_key=self.routing_key,
                        user_message=self.user_message,
                        assistant_reply=reply,
                        turn_ts=self._turn_start_ts,
                        db_dsn=self._db_dsn,
                        messages=_conv_msgs,
                        fragment_type=_frag_type,
                    )
                )
                self._index_tasks.add(index_task)
                index_task.add_done_callback(self._index_tasks.discard)

            # 远程长期记忆双写（fire-and-forget，与 pgvector 索引互不影响）
            if getattr(self._flags, "enable_remote_memory", False):
                # Phase C2: 统一双写（enable_memory_sync 门控）
                if getattr(self._flags, "enable_memory_sync", False):
                    from xiaopaw.memory.memory_sync import get_sync_manager
                    # 进程级单例：保证 full_sync 锁跨回合互斥
                    sync_mgr = get_sync_manager(remote_memory_store, self._db_dsn)
                    sync_task = asyncio.get_running_loop().create_task(
                        sync_mgr.write_through(
                            session_id=self.session_id,
                            routing_key=self.routing_key,
                            user_message=self.user_message,
                            assistant_reply=reply,
                            turn_ts=self._turn_start_ts,
                            fragment_type=_frag_type,
                        )
                    )
                    self._index_tasks.add(sync_task)
                    sync_task.add_done_callback(self._index_tasks.discard)
                elif getattr(self._flags, "enable_memory_extraction", False):
                    # Phase A1: LLM 驱动的结构化记忆抽取（失败降级到 save_turn）
                    messages_for_extraction = [
                        {"role": "user", "content": self.user_message},
                        {"role": "assistant", "content": reply},
                    ]
                    extract_task = asyncio.get_running_loop().create_task(
                        self._extract_or_fallback(
                            self.session_id, messages_for_extraction, reply,
                            fragment_type=_frag_type,
                        )
                    )
                    self._index_tasks.add(extract_task)
                    extract_task.add_done_callback(self._index_tasks.discard)
                else:
                    remote_memory_store.save_turn_background(
                        session_id=self.session_id,
                        routing_key=self.routing_key,
                        user_message=self.user_message,
                        assistant_reply=reply,
                        fragment_type=_frag_type,
                    )

            # Phase C1: 图谱摄取（fire-and-forget，需同时开启 remote_memory + graph_memory）
            if (
                getattr(self._flags, "enable_remote_memory", False)
                and getattr(self._flags, "enable_graph_memory", False)
            ):
                graph_task = asyncio.get_running_loop().create_task(
                    remote_memory_store.graph_ingest(
                        self.user_message, session_id=self.session_id,
                    )
                )
                self._index_tasks.add(graph_task)
                graph_task.add_done_callback(self._index_tasks.discard)

            return reply, used_skills
        finally:
            try:
                unregister_before_tool_call_hook(self.before_tool_hook)
            except (ValueError, AttributeError):
                pass

    @staticmethod
    def _cleanup_crewai_db_locks() -> None:
        """Remove stale WAL/SHM lock files that can block SQLite reopening."""
        try:
            from crewai_core.paths import db_storage_path
            db_dir = Path(db_storage_path())
            for suffix in ("-wal", "-shm"):
                lock_file = db_dir / f"latest_kickoff_task_outputs.db{suffix}"
                if lock_file.exists() and lock_file.stat().st_size == 0:
                    lock_file.unlink(missing_ok=True)
                    logger.info("removed stale CrewAI DB lock file: %s", lock_file)
        except Exception as e:
            logger.debug("cleanup_crewai_db_locks: %s", e)

    async def _extract_or_fallback(
        self, session_id: str, messages: list[dict], reply: str,
        *, fragment_type: str = "info",
    ) -> None:
        """Phase A1: 调用 extract_and_save，失败时降级到 save_turn_background。"""
        try:
            result = await remote_memory_store.extract_and_save(session_id, messages)
            if not result.get("saved"):
                # extraction 失败，降级到普通 save_turn
                logger.info(
                    "extraction returned 0 saved, falling back to save_turn for session %s",
                    session_id,
                )
                remote_memory_store.save_turn_background(
                    session_id=session_id,
                    routing_key=self.routing_key,
                    user_message=self.user_message,
                    assistant_reply=reply,
                    fragment_type=fragment_type,
                )
        except Exception as exc:
            logger.warning("extract_or_fallback failed, falling back: %s", exc)
            remote_memory_store.save_turn_background(
                session_id=session_id,
                routing_key=self.routing_key,
                user_message=self.user_message,
                assistant_reply=reply,
                fragment_type=fragment_type,
            )

    @staticmethod
    def _format_layered_recall(layered: dict) -> str:
        """格式化三层召回结果为文本。

        Level 1 (profile) 始终包含在头部。
        Level 2 (semantic) 作为主体内容。
        Level 3 (entity_expansion) 追加在末尾。
        """
        parts: list[str] = []
        if layered.get("profile"):
            parts.append(f"[用户画像]\n{layered['profile']}")
        if layered.get("semantic"):
            parts.append(f"[相关记忆]\n{layered['semantic']}")
        if layered.get("entity_expansion"):
            parts.append(f"[关联信息]\n{layered['entity_expansion']}")
        return "\n\n".join(parts) if parts else ""


def build_agent_fn(
    sender: SenderProtocol,
    workspace_dir: Path,
    ctx_dir: Path,
    db_dsn: str = "",
    max_history_turns: int = _DEFAULT_MAX_HISTORY_TURNS,
    sandbox_url: str = "",
    flags: FeatureFlags | None = None,
    skill_registry: Any | None = None,
    user_skills_dir: Path | None = None,
    sandbox_pool: Any | None = None,
) -> AgentFn:
    ctx_dir.mkdir(parents=True, exist_ok=True)

    async def agent_fn(
        user_message: str,
        history: list[MessageEntry],
        session_id: str,
        routing_key: str = "",
        verbose: bool = False,
    ) -> tuple[str, list[str]]:
        # 动态定位用户 workspace
        user_ws = workspace_dir  # 默认全局
        if routing_key.startswith("p2p:web_"):
            username = routing_key[len("p2p:web_"):]
            candidate = workspace_dir / username
            if candidate.is_dir():
                user_ws = candidate

        # 短期#9：会话级沙箱 —— 从池中取本会话专属沙箱，失败自动回退共享沙箱
        turn_sandbox_url = sandbox_url
        if sandbox_pool is not None:
            turn_sandbox_url = await sandbox_pool.acquire(session_id)

        # 远程长期记忆召回预取（async 环境，避免在同步 hook 内跑事件循环）；
        # 失败/超时返回空串，不阻断对话
        recalled_memory = ""
        user_preferences: dict = {}
        if (
            flags is not None
            and getattr(flags, "enable_remote_memory", False)
            and remote_memory_store.is_enabled
        ):
            # Phase B1: 分层召回（enable_layered_recall flag 门控）
            if getattr(flags, "enable_layered_recall", False):
                layered = await remote_memory_store.recall_layered(
                    user_message, token_budget=4000,
                )
                recalled_memory = MemoryAwareCrew._format_layered_recall(layered)
            else:
                recalled_memory = await remote_memory_store.recall(
                    query=user_message, routing_key=routing_key
                )
            # Phase 4 FR-1：已存偏好合并读取（失败返回空 dict 不阻断）
            user_preferences = await remote_memory_store.get_preferences(
                routing_key=routing_key
            )

            # Phase C1: 图谱查询 —— 召回阶段查询实体关系，注入 prompt 上下文
            if getattr(flags, "enable_graph_query", False):
                try:
                    graph_results = await remote_memory_store.graph_query(
                        entity=user_message, depth=2,
                    )
                    if graph_results:
                        graph_lines = []
                        for rel in graph_results:
                            graph_lines.append(
                                f"- {rel.get('entity', '')} → {rel.get('relation', '')} → {rel.get('target', '')}"
                            )
                        graph_text = "\n".join(graph_lines)
                        recalled_memory += (
                            "\n\n<graph_knowledge>\n"
                            "以下为用户消息中实体的图谱关联信息：\n"
                            f"{graph_text}\n"
                            "</graph_knowledge>"
                        )
                        logger.info(
                            "graph_query returned %d relations for session %s",
                            len(graph_results), session_id,
                        )
                except Exception as exc:
                    logger.warning("graph_query in recall phase failed (degraded): %s", exc)

        crew_instance = MemoryAwareCrew(
            session_id=session_id,
            routing_key=routing_key,
            user_message=user_message,
            sender=sender,
            workspace_dir=user_ws,
            ctx_dir=ctx_dir,
            history_all=history,
            db_dsn=db_dsn,
            max_history_turns=max_history_turns,
            sandbox_url=turn_sandbox_url,
            flags=flags,
            skill_registry=skill_registry,
            user_skills_dir=user_skills_dir,
            recalled_memory=recalled_memory,
            user_preferences=user_preferences,
            verbose=verbose,
        )
        return await crew_instance.run_and_index()

    return agent_fn
