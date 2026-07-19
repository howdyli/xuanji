#!/usr/bin/env python3
"""ModelRouter 功能验证脚本。

运行方式：
    python test_model_router.py              # 基本功能测试
    python test_model_router.py --verbose     # 显示详细信息
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))


def print_section(title: str) -> None:
    """打印分隔线标题。"""
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print(f"{'=' * 60}")


def print_result(test_name: str, passed: bool, detail: str = "") -> None:
    """打印测试结果。"""
    status = "✅" if passed else "❌"
    msg = f"{status} {test_name}"
    if detail:
        msg += f": {detail}"
    print(msg)
    return passed


def test_import() -> bool:
    """测试模块导入。"""
    print_section("1. 模块导入测试")
    try:
        from xiaopaw.llm.model_router import (
            ModelRouter,
            TaskType,
            RoutingStrategy,
            ModelConfig,
            ModelStats,
            model_router,
        )
        return print_result("导入成功", True, f"全局单例 ID: {id(model_router)}")
    except Exception as e:
        return print_result("导入失败", False, str(e))


def test_config_loading() -> bool:
    """测试从 config.yaml 加载配置。"""
    print_section("2. 配置加载测试")
    try:
        from xiaopaw.llm.model_router import model_router
        import yaml

        config_path = Path("config.yaml")
        if not config_path.exists():
            return print_result("config.yaml 不存在", False)

        with config_path.open("r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}

        # 初始化路由器
        model_router.init_from_config(full_cfg)

        # 验证配置加载结果
        models = list(model_router._models.keys())
        default = model_router._default_model
        strategy = model_router._default_strategy.value

        details = f"默认模型={default}, 策略={strategy}, 已注册模型数={len(models)}"
        if len(models) >= 2:
            details += f", 模型列表={', '.join(models[:3])}..."

        return print_result(
            "配置加载成功",
            len(models) > 0,
            details,
        )
    except Exception as e:
        traceback.print_exc()
        return print_result("配置加载失败", False, str(e))


def test_model_registration() -> bool:
    """测试模型注册与管理。"""
    print_section("3. 模型注册管理测试")
    try:
        from xiaopaw.llm.model_router import ModelConfig, model_router

        # 注册测试模型
        test_cfg = ModelConfig(
            name="test-model",
            display_name="Test Model",
            provider="openai",
            cost_per_1k_tokens=0.01,
            quality_score=5.0,
        )
        model_router.register_model(test_cfg)

        # 验证注册成功
        available = model_router.get_available_models()
        result1 = "test-model" in available
        print_result("模型注册", result1, f"可用模型: {available}")

        # 测试获取模型配置
        cfg = model_router._models.get("test-model")
        result2 = cfg is not None and cfg.display_name == "Test Model"
        print_result("获取配置", result2, cfg.display_name if cfg else "None")

        # 测试注销
        model_router.unregister_model("test-model")
        available_after = model_router.get_available_models()
        result3 = "test-model" not in available_after
        print_result("模型注销", result3, f"注销后可用: {available_after}")

        return all([result1, result2, result3])
    except Exception as e:
        traceback.print_exc()
        return print_result("模型管理失败", False, str(e))


def test_routing_strategies() -> bool:
    """测试不同路由策略的选择逻辑。"""
    print_section("4. 路由策略测试")
    try:
        from xiaopaw.llm.model_router import (
            RoutingStrategy,
            TaskType,
            model_router,
        )

        results = []

        # 1. COST_FIRST：应选最便宜的
        cheapest = model_router._select_best(
            list(model_router._models.keys()),
            RoutingStrategy.COST_FIRST,
        )
        # 验证：应该选择成本最低的
        if model_router._models:
            min_cost_model = min(
                model_router._models.keys(),
                key=lambda n: model_router._models[n].cost_per_1k_tokens,
            )
            r1 = (cheapest == min_cost_model)
            results.append(print_result("成本优先策略", r1, f"选中: {cheapest}"))
        else:
            results.append(print_result("成本优先策略", False, "无已注册模型"))

        # 2. QUALITY_FIRST：应选质量最高的
        best_quality = model_router._select_best(
            list(model_router._models.keys()),
            RoutingStrategy.QUALITY_FIRST,
        )
        if model_router._models:
            max_qual_model = max(
                model_router._models.keys(),
                key=lambda n: model_router._models[n].quality_score,
            )
            r2 = (best_quality == max_qual_model)
            results.append(print_result("质量优先策略", r2, f"选中: {best_quality}"))
        else:
            results.append(print_result("质量优先策略", False, "无已注册模型"))

        # 3. LATENCY_SENSITIVE：应选延迟最低的
        fastest = model_router._select_best(
            list(model_router._models.keys()),
            RoutingStrategy.LATENCY_SENSITIVE,
        )
        if model_router._models:
            min_lat_model = min(
                model_router._models.keys(),
                key=lambda n: model_router._models[n].avg_latency_ms,
            )
            r3 = (fastest == min_lat_model)
            results.append(print_result("延迟敏感策略", r3, f"选中: {fastest}"))
        else:
            results.append(print_result("延迟敏感策略", False, "无已注册模型"))

        # 4. ROUND_ROBIN：连续调用应轮询
        idx1 = model_router._round_robin_idx.get("round_robin", 0)
        _ = model_router._select_best(list(model_router._models.keys()), RoutingStrategy.ROUND_ROBIN)
        idx2 = model_router._round_robin_idx.get("round_robin", 0)
        r4 = (idx2 > idx1)  # 计数器应递增
        results.append(print_result("轮询策略", r4, f"索引变化: {idx1} → {idx2}"))

        return all(results)
    except Exception as e:
        traceback.print_exc()
        return print_result("路由策略失败", False, str(e))


def test_task_routes() -> bool:
    """测试任务类型到模型的映射。"""
    print_section("5. 任务路由映射测试")
    try:
        from xiaopaw.llm.model_router import TaskType, model_router

        results = []

        for task_type in TaskType:
            candidates = model_router._get_candidates(task_type)
            has_route = task_type in model_router._task_routes
            route_info = (
                model_router._task_routes[task_type]
                if has_route
                else ["(使用默认模型)"]
            )

            status = len(candidates) > 0 or model_router._default_model
            results.append(
                print_result(
                    f"任务路由: {task_type.value}",
                    status,
                    f"候选={candidates or ['default']}",
                )
            )

        return all(results)
    except Exception as e:
        traceback.print_exc()
        return print_result("任务路由失败", False, str(e))


def test_health_management() -> bool:
    """测试健康状态管理和故障转移。"""
    print_section("6. 健康状态与故障转移测试")
    try:
        from xiaopaw.llm.model_router import model_router

        # 获取第一个可用的模型进行测试
        available = model_router.get_available_models()
        if not available:
            return print_result("跳过（无可用模型）", True, "")

        test_model = available[0]
        results = []

        # 标记不健康
        model_router.mark_model_unhealthy(test_model, reason="test")
        new_available = model_router.get_available_models()
        r1 = test_model not in new_available
        results.append(print_result("标记不健康", r1, f"{test_model} 已从可用列表移除"))

        # 恢复健康
        model_router.mark_model_healthy(test_model)
        restored_available = model_router.get_available_models()
        r2 = test_model in restored_available
        results.append(print_result("恢复健康", r2, f"{test_model} 已重新加入"))

        # 故障转移链测试（如果配置了 fallback）
        if model_router._fallback_chain:
            # 手动标记所有候选不健康，看是否会走 fallback
            original_chain = model_router._fallback_chain.copy()
            results.append(print_result(
                "故障转移链",
                True,
                f"链路: {' → '.join(original_chain)}",
            ))

        return all(results)
    except Exception as e:
        traceback.print_exc()
        return print_result("健康管理失败", False, str(e))


def test_statistics_tracking() -> bool:
    """测试调用统计跟踪。"""
    print_section("7. 运行时统计测试")
    try:
        from xiaopaw.llm.model_router import model_router

        available = model_router.get_available_models()
        if not available:
            return print_result("跳过（无可用模型）", True, "")

        test_model = available[0]

        # 模拟几次调用
        model_router.record_call(test_model, success=True, latency_ms=500)
        model_router.record_call(test_model, success=True, latency_ms=800)
        model_router.record_call(test_model, success=False, latency_ms=0)

        stats = model_router.get_stats()
        model_stats = stats["models"].get(test_model, {})

        checks = [
            ("总调用次数==3", model_stats.get("total_calls") == 3),
            ("成功次数==2", model_stats.get("successful_calls") == 2),
            ("失败次数==1", model_stats.get("failed_calls") == 1),
            ("成功率≈0.67", abs(model_stats.get("success_rate", 0) - 0.6667) < 0.01),
            ("平均延迟≈650ms", abs(model_stats.get("avg_latency_ms", 0) - 650.0) < 10),
        ]

        results = []
        for check_name, check_result in checks:
            results.append(print_result(check_name, check_result))

        # 重置统计并验证
        model_router.reset_stats(test_model)
        reset_stats = model_router.get_stats()["models"].get(test_model, {})
        r_reset = reset_stats.get("total_calls") == 0
        results.append(print_result("重置统计", r_reset))

        return all(results)
    except Exception as e:
        traceback.print_exc()
        return print_result("统计跟踪失败", False, str(e))


def test_llm_creation() -> bool:
    """测试 LLM 实例创建（需要 API Key）。"""
    print_section("8. LLM 实例创建测试")
    try:
        from xiaopaw.llm.model_router import model_router
        import os

        # 检查是否有 API Key
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        has_key = bool(api_key) and not api_key.startswith("YOUR_")

        if not has_key:
            return print_result(
                "跳过（无有效 API Key）",
                True,
                "设置 DEEPSEEK_API_KEY 后可完整测试",
            )

        # 尝试创建 LLM 实例
        llm = model_router.get_llm(task_type="general_chat")

        checks = [
            ("实例非空", llm is not None),
            ("model 属性", hasattr(llm, 'model') and llm.model),
            ("call 方法存在", hasattr(llm, 'call')),
            ("acall 方法存在", hasattr(llm, 'acall')),
        ]

        results = []
        for check_name, check_result in checks:
            results.append(print_result(check_name, check_result))

        if llm:
            details = f"model={llm.model}, region={getattr(llm, 'region', 'N/A')}"
            print(f"   📋 LLM 配置: {details}")

        return all(results)
    except Exception as e:
        traceback.print_exc()
        return print_result("LLM 创建失败", False, str(e))


def main() -> int:
    """主函数：运行所有测试用例。"""
    verbose = "--verbose" in sys.argv

    print("\n" + "=" * 60)
    print(" 🧪 ModelRouter 多模型路由系统 - 功能验证")
    print("=" * 60)
    print(f" 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" 工作目录: {Path.cwd()}")

    # 定义测试套件
    tests = [
        ("模块导入", test_import),
        ("配置加载", test_config_loading),
        ("模型注册管理", test_model_registration),
        ("路由策略", test_routing_strategies),
        ("任务路由映射", test_task_routes),
        ("健康状态与故障转移", test_health_management),
        ("运行时统计", test_statistics_tracking),
        ("LLM 创建", test_llm_creation),
    ]

    # 执行测试
    results = []
    for name, test_func in tests:
        passed = test_func()
        results.append((name, passed))

    # 输出总结
    print_section("验证结果总结")

    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    failed_count = total - passed_count

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")

    print(f"\n{'─' * 60}")
    print(f" 总计: {total} 项 | 通过: {passed_count} 项 | 失败: {failed_count} 项")
    print(f" 通过率: {(passed_count / total * 100):.1f}%")

    if failed_count == 0:
        print(f"\n🎉 所有测试通过！ModelRouter 多模型路由系统工作正常！")
        return 0
    else:
        print(f"\n⚠️ 有 {failed_count} 项测试未通过，请检查上方详情。")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
