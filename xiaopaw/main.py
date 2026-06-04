"""玄机 entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from xiaopaw.config.safety import assert_all_production_safe
from xiaopaw.config.validator import load_config
from xiaopaw.observability.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    config_path = Path(os.environ.get("XIAOPAW_CONFIG", "config.yaml"))
    cfg = load_config(config_path)

    is_dev = os.environ.get("XIAOPAW_ENV", "dev") == "dev"
    data_dir = Path(cfg.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(
        log_dir=data_dir / "logs",
        json_output=cfg.observability.log_json,
    )

    assert_all_production_safe(cfg, is_dev=is_dev)

    # Import after logging is configured
    from xiaopaw.agents.main_crew import build_agent_fn
    from xiaopaw.api.capture_sender import CaptureSender
    from xiaopaw.cleanup.service import CleanupService
    from xiaopaw.cron.service import CronService
    from xiaopaw.hook_framework.loader import HookLoader
    from xiaopaw.hook_framework.registry import HookRegistry
    from xiaopaw.observability.metrics_server import start_metrics_server
    from xiaopaw.observability.security import RateLimiter, ReplayCache
    from xiaopaw.runner import Runner
    from xiaopaw.session.manager import SessionManager

    # Frontend PostgreSQL store (optional, gracefully falls back)
    pg_store = None
    if cfg.frontend.enabled and cfg.memory.db_dsn:
        from xiaopaw.frontend.store import PGStore
        pg_store = PGStore(dsn=cfg.memory.db_dsn)

    # Skill registry (scans builtin + user dirs, syncs metadata to DB if available)
    skill_registry = None
    user_skills_dir: Path | None = None
    market_registry = None
    market_sync = None
    if cfg.frontend.enabled:
        from xiaopaw.skills_mgmt.market import MarketRegistry, MarketSync
        from xiaopaw.skills_mgmt.registry import SkillRegistry
        user_skills_dir = Path(cfg.skills.user_dir)
        if not user_skills_dir.is_absolute():
            user_skills_dir = Path(__file__).resolve().parent.parent / cfg.skills.user_dir
        skill_registry = SkillRegistry(
            builtin_dir=Path(__file__).resolve().parent / "skills",
            user_dir=user_skills_dir,
            pg_store=pg_store,
        )
        skill_registry.sync_to_db()

        # Market layer: works with or without PG (falls back to in-memory cache).
        if cfg.skill_market.enabled:
            market_sync = MarketSync(
                pg_store=pg_store,
                vercel_index_url=cfg.skill_market.vercel_index_url,
                clawhub_index_url=cfg.skill_market.clawhub_index_url,
                fetch_timeout_seconds=cfg.skill_market.fetch_timeout_seconds,
            )
            market_registry = MarketRegistry(
                pg_store=pg_store,
                skill_registry=skill_registry,
                install_max_bytes=cfg.skill_market.install_max_bytes,
                fetch_timeout_seconds=cfg.skill_market.fetch_timeout_seconds,
                market_sync=market_sync,
            )

    session_mgr = SessionManager(
        data_dir=data_dir,
        max_active_sessions=cfg.session.max_active_sessions,
    )

    workspace_dir = Path(cfg.workspace)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    ctx_dir = data_dir / "ctx"

    # Workspace init: copy template files from workspace-init/ if missing (fresh user).
    # Sandbox gem (UID 1000) needs to write workspace files; root-owned 644 blocks
    # memory-save → LLM "creatively" writes to alternate path → Skill returns success
    # but Bootstrap never sees it. Force 0o666 on every startup to prevent this trap.
    workspace_init_dir = Path(__file__).parent.parent / "workspace-init"
    if workspace_init_dir.exists():
        import shutil
        workspace_dir.chmod(0o777)
        for src in workspace_init_dir.iterdir():
            if not src.is_file():
                continue
            dest = workspace_dir / src.name
            if not dest.exists():
                shutil.copy2(src, dest)
                logger.info("workspace init: copied %s to workspace", src.name)
        for f in workspace_dir.glob("*.md"):
            try:
                f.chmod(0o666)
            except OSError as e:
                logger.warning("workspace chmod 666 failed for %s: %s", f.name, e)

    # Build Feishu sender or capture sender
    if is_dev and cfg.debug.enable_test_api:
        sender = CaptureSender()
    else:
        import lark_oapi as lark
        lark_client = lark.Client.builder() \
            .app_id(cfg.feishu.app_id) \
            .app_secret(cfg.feishu.app_secret) \
            .build()
        from xiaopaw.feishu.sender import FeishuSender
        sender = FeishuSender(
            client=lark_client,
            max_retries=cfg.sender.max_retries,
            retry_backoff=tuple(cfg.sender.retry_backoff),
            max_concurrent=cfg.sender.max_concurrent,
        )

    agent_fn = build_agent_fn(
        sender=sender,
        workspace_dir=workspace_dir,
        ctx_dir=ctx_dir,
        db_dsn=cfg.memory.db_dsn,
        max_history_turns=cfg.session.max_history_turns,
        sandbox_url=cfg.sandbox.url,
        flags=cfg.feature_flags,
        skill_registry=skill_registry,
        user_skills_dir=user_skills_dir,
    )

    # Load Hook framework (v3 layer)
    hook_registry = HookRegistry()
    hook_loader = HookLoader(hook_registry)
    shared_hooks_dir = Path(__file__).parent.parent / "shared_hooks"
    fail_closed = {"sandbox_guard", "permission_gate"}
    hook_loader.load_two_layers(
        global_dir=shared_hooks_dir,
        workspace_dir=workspace_dir,
        fail_closed_names=fail_closed,
    )
    logger.info("hook framework loaded: %s", hook_registry.summary())

    runner = Runner(
        session_mgr=session_mgr,
        sender=sender,
        agent_fn=agent_fn,
        idle_timeout=cfg.runner.idle_timeout_s,
        max_queue_size=cfg.runner.max_queue_size,
        data_dir=data_dir,
        hook_registry=hook_registry,
    )

    # Start metrics server
    metrics_runner = await start_metrics_server(
        host=cfg.observability.metrics_host,
        port=cfg.observability.metrics_port,
    )

    # Start cron service
    from xiaopaw.cron.automation import AutomationRegistry
    automation_registry = AutomationRegistry(
        db_path=data_dir / "auth.db",
        data_dir=data_dir,
    )
    cron_storage = automation_registry.storage
    cron_svc = CronService(
        storage=cron_storage,
        dispatch_fn=runner.dispatch,
        check_interval=cfg.cron.check_interval_s,
    )
    if cfg.cron.enabled:
        await cron_svc.start()

    # Start cleanup service
    cleanup_svc = CleanupService(
        data_dir=data_dir,
        session_ttl_days=cfg.cleanup.session_ttl_days,
        trace_ttl_days=cfg.cleanup.trace_ttl_days,
        raw_ttl_days=cfg.cleanup.raw_ttl_days,
        run_hour_utc=cfg.cleanup.run_hour_utc,
    )
    if cfg.cleanup.enabled:
        await cleanup_svc.start()

    # Start market sync background task (every sync_interval_hours).
    # Inline asyncio task; first run is delayed 5s so PG handshake completes.
    market_sync_task: asyncio.Task | None = None
    if market_sync is not None:
        async def _market_sync_loop() -> None:
            await asyncio.sleep(5.0)
            interval = cfg.skill_market.sync_interval_hours * 3600
            while True:
                try:
                    await market_sync.sync_to_db()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("market sync failed")
                await asyncio.sleep(interval)

        market_sync_task = asyncio.create_task(
            _market_sync_loop(), name="market-sync"
        )
        logger.info(
            "market sync scheduled (interval=%.1fh)",
            cfg.skill_market.sync_interval_hours,
        )

    # Start TestAPI (dev only)
    test_api_runner = None
    if is_dev and cfg.debug.enable_test_api:
        from aiohttp import web
        from xiaopaw.api.test_server import create_test_app
        test_app = create_test_app(
            runner=runner,
            sender=sender,
            session_mgr=session_mgr,
            token=cfg.debug.test_api_token,
        )
        test_api_runner = web.AppRunner(test_app)
        await test_api_runner.setup()
        site = web.TCPSite(
            test_api_runner, cfg.debug.test_api_host, cfg.debug.test_api_port
        )
        await site.start()
        logger.info(
            "TestAPI listening on %s:%d",
            cfg.debug.test_api_host, cfg.debug.test_api_port,
        )

    # Start Frontend server (static files + REST API)
    frontend_runner = None
    if cfg.frontend.enabled:
        from xiaopaw.frontend.auth import UserAuth
        from xiaopaw.frontend.server import create_frontend_app

        # Initialize user auth (SQLite)
        user_auth = UserAuth(data_dir / "auth.db")

        # Initialize expert registry (reuses auth.db)
        from xiaopaw.frontend.expert import ExpertRegistry
        expert_registry = ExpertRegistry(data_dir / "auth.db")

        # Initialize channel manager (LLM provider management)
        from xiaopaw.llm.channel_manager import ChannelManager
        channel_manager = ChannelManager(config_path=data_dir / "channels.json")

        frontend_app = create_frontend_app(
            runner=runner,
            sender=sender,
            session_mgr=session_mgr,
            pg_store=pg_store,
            token=cfg.debug.test_api_token,
            skill_registry=skill_registry,
            skills_max_upload_bytes=cfg.skills.max_upload_mb * 1024 * 1024,
            market_registry=market_registry,
            market_sync=market_sync,
            workspace_dir=str(workspace_dir.resolve()),
            user_auth=user_auth,
            expert_registry=expert_registry,
            automation_registry=automation_registry,
            channel_manager=channel_manager,
        )
        frontend_runner = web.AppRunner(frontend_app)
        await frontend_runner.setup()
        fe_site = web.TCPSite(
            frontend_runner, cfg.frontend.host, cfg.frontend.port
        )
        await fe_site.start()
        logger.info(
            "Frontend listening on http://%s:%d",
            cfg.frontend.host, cfg.frontend.port,
        )

    # Start Feishu listener (production)
    feishu_listener = None
    if not (is_dev and cfg.debug.enable_test_api):
        from xiaopaw.feishu.listener import FeishuListener
        replay_cache = ReplayCache(
            maxsize=cfg.replay_cache.maxsize, ttl_sec=cfg.replay_cache.ttl_sec
        )
        rate_limiter = RateLimiter(per_user_per_minute=cfg.rate_limit.per_user_per_minute)
        feishu_listener = FeishuListener(
            app_id=cfg.feishu.app_id,
            app_secret=cfg.feishu.app_secret,
            on_message=runner.dispatch,
            replay_cache=replay_cache,
            rate_limiter=rate_limiter,
            allowed_chats=cfg.feishu.allowed_chats or None,
        )
        await feishu_listener.start()

    logger.info("玄机 started (env=%s)", "dev" if is_dev else "production")

    # Wait for shutdown signal
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    logger.info("shutdown signal received")

    # Graceful shutdown
    if feishu_listener:
        await feishu_listener.stop()
    await cron_svc.stop()
    await cleanup_svc.stop()
    if market_sync_task is not None:
        market_sync_task.cancel()
        try:
            await market_sync_task
        except asyncio.CancelledError:
            pass
    await runner.shutdown()
    if test_api_runner:
        await test_api_runner.cleanup()
    if frontend_runner:
        await frontend_runner.cleanup()
    if pg_store:
        pg_store.close()
    await metrics_runner.cleanup()

    logger.info("XiaoPaw v2 shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
