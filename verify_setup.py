#!/usr/bin/env python3
"""
验证 XiaoPaw v2 服务和 DeepSeek 配置是否正常
"""

import os
import sys
from pathlib import Path

def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_pass(message: str):
    print(f"  ✅ {message}")

def check_fail(message: str, error: str = ""):
    print(f"  ❌ {message}")
    if error:
        print(f"     错误: {error}")

def main():
    all_passed = True
    
    print_section("XiaoPaw v2 服务验证")
    
    # 1. 检查环境变量
    print_section("1. 环境变量检查")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if deepseek_key:
        check_pass(f"DEEPSEEK_API_KEY 已设置 ({deepseek_key[:15]}...)")
    else:
        check_fail("DEEPSEEK_API_KEY 未设置")
        all_passed = False
    
    # 2. 检查配置文件
    print_section("2. 配置文件检查")
    config_files = {
        ".env": "环境变量文件",
        "config.yaml": "主配置文件",
        "config.yaml.example": "配置示例文件",
    }
    
    for filename, desc in config_files.items():
        if Path(filename).exists():
            check_pass(f"{filename} ({desc}) 存在")
        else:
            check_fail(f"{filename} ({desc}) 不存在")
            all_passed = False
    
    # 3. 检查模块导入
    print_section("3. 核心模块导入检查")
    modules = [
        ("xiaopaw.llm.aliyun_llm", "AliyunLLM"),
        ("xiaopaw.agents.main_crew", "MemoryAwareCrew"),
        ("xiaopaw.agents.skill_crew", "build_skill_crew"),
        ("xiaopaw.config.validator", "load_config"),
        ("xiaopaw.hook_framework.registry", "HookRegistry"),
    ]
    
    for module_path, class_name in modules:
        try:
            module = __import__(module_path, fromlist=[class_name])
            getattr(module, class_name)
            check_pass(f"{module_path}.{class_name}")
        except Exception as e:
            check_fail(f"{module_path}.{class_name}", str(e))
            all_passed = False
    
    # 4. 检查 LLM 配置
    print_section("4. LLM 配置检查")
    try:
        from xiaopaw.llm.aliyun_llm import AliyunLLM
        
        llm = AliyunLLM(model='deepseek-v4-flash', region='deepseek')
        check_pass(f"模型: {llm.model}")
        check_pass(f"端点: {llm.endpoint}")
        check_pass(f"API Key: {llm.api_key[:15]}...")
        check_pass(f"Region: {llm.region}")
        check_pass(f"Timeout: {llm.timeout}s")
        
        if "api.deepseek.com" not in llm.endpoint:
            check_fail("端点地址不正确")
            all_passed = False
    except Exception as e:
        check_fail("LLM 初始化失败", str(e))
        all_passed = False
    
    # 5. 检查配置文件加载
    print_section("5. 配置文件加载检查")
    try:
        from xiaopaw.config.validator import load_config
        
        config = load_config(Path('config.yaml'))
        check_pass(f"Agent 模型: {config.agent.model}")
        check_pass(f"Sub-Agent 模型: {config.agent.sub_agent_model}")
        check_pass(f"最大迭代次数: {config.agent.max_iter}")
        check_pass(f"超时时间: {config.agent.timeout_s}s")
        
        if config.agent.model != "deepseek-v4-flash":
            check_fail("配置文件中模型不是 deepseek-v4-flash")
            all_passed = False
    except Exception as e:
        check_fail("配置文件加载失败", str(e))
        all_passed = False
    
    # 6. 检查目录结构
    print_section("6. 目录结构检查")
    dirs = [
        "xiaopaw",
        "tests",
        "docs",
        "workspace-init",
    ]
    
    for dir_name in dirs:
        if Path(dir_name).is_dir():
            check_pass(f"{dir_name}/ 目录存在")
        else:
            check_fail(f"{dir_name}/ 目录不存在")
            all_passed = False
    
    # 最终结果
    print_section("验证结果")
    if all_passed:
        print("\n  🎉 所有验证通过！服务配置正确！\n")
        print("  下一步操作：")
        print("  1. 启动主服务: python -m xiaopaw.main")
        print("  2. 运行测试: pytest tests/unit -v")
        print("  3. 查看文档: docs/01-architecture.md")
        print()
        return 0
    else:
        print("\n  ⚠️  部分验证失败，请检查上面的错误信息\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
