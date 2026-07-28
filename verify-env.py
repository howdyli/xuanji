#!/usr/bin/env python3
"""
XiaoPaw v2 环境变量验证脚本
用于检查 DEEPSEEK_API_KEY 和 FEISHU_APP_SECRET 是否正确配置

用法:
    python verify-env.py [--verbose] [--check-api]

选项:
    --verbose      显示详细信息（包括部分密钥内容）
    --check-api    验证 API Key 是否有效（会发起真实网络请求）
"""

import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    print("⚠️  未安装 python-dotenv，请执行: pip install python-dotenv")
    load_dotenv = None


def check_env_file_exists():
    """检查 .env 文件是否存在"""
    env_file = Path(".env")
    if not env_file.exists():
        return False, ".env 文件不存在"
    
    if not env_file.is_file():
        return False, ".env 不是文件"
    
    # 检查文件大小
    size = env_file.stat().st_size
    if size < 10:
        return False, f".env 文件过小 ({size} bytes)"
    
    return True, f".env 文件存在 ({size} bytes)"


def load_environment():
    """加载环境变量"""
    success, msg = check_env_file_exists()
    if not success:
        print(f"❌ {msg}")
        
        # 尝试从系统环境变量读取
        key = os.getenv('DEEPSEEK_API_KEY', '')
        secret = os.getenv('FEISHU_APP_SECRET', '')
        if key or secret:
            print("ℹ️  从系统环境变量中检测到部分配置")
            return key, secret
        
        return None, None
    
    if load_dotenv:
        load_dotenv()
        print("✅ 已从 .env 文件加载环境变量")
    else:
        print("⚠️  无法自动加载 .env，使用系统环境变量")
    
    return os.getenv('DEEPSEEK_API_KEY', ''), os.getenv('FEISHU_APP_SECRET', '')


def validate_api_key(key):
    """验证 DeepSeek API Key 格式"""
    issues = []
    
    if not key:
        issues.append(("critical", "API Key 为空"))
        return issues
    
    # 检查是否为占位符
    placeholders = [
        'YOUR_DEEPSEEK_API_KEY_HERE',
        'your-api-key',
        'sk-xxxxxxxxxxxx',
        'YOUR_KEY_HERE'
    ]
    
    for ph in placeholders:
        if key.lower() == ph.lower() or ph.lower() in key.lower():
            issues.append(("error", "仍为占位符文本，未替换为真实密钥"))
            return issues
    
    # 检查格式：应以 sk- 开头
    if not key.startswith('sk-'):
        issues.append(("warning", f"格式异常：应以 sk- 开头，当前以 {key[:5]} 开头"))
    
    # 检查长度（DeepSeek Key 通常为 48 字符）
    if len(key) < 20:
        issues.append(("error", f"长度过短：{len(key)} 字符（通常应为 48 字符）"))
    elif len(key) > 60:
        issues.append(("warning", f"长度过长：{len(key)} 字符（通常应为 48 字符）"))
    
    # 检查是否包含非法字符
    if re.search(r'[\s\n\r\t]', key):
        issues.append(("error", "包含空白字符或换行符（复制时可能出错）"))
    
    # 检查是否为旧泄露的密钥
    LEAKED_KEY_PREFIX = 'sk-5a78c12f1ad249828c88c11d60725512'
    if key.startswith(LEAKED_KEY_PREFIX[:16]):
        issues.append(("critical", "🚨 检测到已泄露的旧密钥！请立即更换！"))
    
    return issues


def validate_feishu_secret(secret):
    """验证飞书 App Secret 格式"""
    issues = []
    
    if not secret:
        issues.append(("warning", "飞书 App Secret 为空（如不使用飞书功能可忽略）"))
        return issues
    
    # 检查占位符
    if 'YOUR_FEISHU' in secret or secret == 'your-secret':
        issues.append(("error", "仍为占位符文本，未替换为真实密钥"))
        return issues
    
    # 检查是否为旧泄露的密钥
    LEAKED_SECRET_PREFIX = '0xnskGMsslyr1uPPxs79Bepqyv5KHkYY'
    if secret.startswith(LEAKED_SECRET_PREFIX[:10]):
        issues.append(("critical", "🚨 检测到已泄露的旧 Secret！请立即更换！"))
    
    # 基本格式检查（飞书 Secret 通常为 32 位十六进制字符串）
    if len(secret) < 16:
        issues.append(("warning", f"长度较短：{len(secret)} 字符"))
    
    return issues


def test_deepseek_api_key(api_key):
    """测试 DeepSeek API Key 是否有效（会发起真实网络请求）"""
    try:
        import urllib.request
        import urllib.error
        import ssl
        
        url = "https://api.deepseek.com/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        req = urllib.request.Request(url, headers=headers, method='GET')
        
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = response.read().decode('utf-8')
            
        models = json.loads(data)
        
        if 'data' in models and isinstance(models['data'], list):
            model_names = [m.get('id', '') for m in models['data'][:5]]
            return True, f"✅ API Key 有效！可用模型: {', '.join(model_names)}"
        else:
            return False, "响应格式异常"
            
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "❌ API Key 无效（401 Unauthorized）"
        elif e.code == 429:
            return True, "✅ API Key 有效，但触发频率限制（429 Too Many Requests）"
        else:
            return False, f"HTTP 错误: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, f"网络连接失败: {e.reason}"
    except Exception as e:
        return False, f"测试失败: {str(e)}"


def test_agent_memory_service(base_url, api_key):
    """探测远程记忆服务（agent-memory-system）是否可达"""
    try:
        import urllib.request
        import urllib.error

        # base_url 形如 http://localhost:8000/api/v1，health 端点在服务根路径
        root = base_url.split("/api/")[0].rstrip("/")
        req = urllib.request.Request(f"{root}/health", method='GET')
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status < 400:
                return True, f"✅ 记忆服务可达: {root}"
        return False, f"❌ 记忆服务响应异常: {response.status}"
    except urllib.error.HTTPError as e:
        # 404 也说明服务在线（只是无 /health 端点）
        if e.code in (401, 404):
            return True, f"✅ 记忆服务在线（HTTP {e.code}）"
        return False, f"❌ HTTP 错误: {e.code} {e.reason}"
    except Exception as e:
        return False, f"❌ 无法连接记忆服务: {e}"


def main(verbose=False, check_api=False):
    """主函数"""
    
    print("=" * 50)
    print("🔍 XiaoPaw v2 环境变量验证工具")
    print(f"   运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()
    
    # 加载环境变量
    api_key, feishu_secret = load_environment()
    
    if api_key is None and feishu_secret is None:
        print("\n❌ 无法加载任何配置，退出")
        sys.exit(1)
    
    all_passed = True
    
    # 验证 DEEPSEEK_API_KEY
    print("-" * 50)
    print("📌 DEEPSEEK_API_KEY 检查:")
    print("-" * 50)
    
    key_issues = validate_api_key(api_key)
    
    if not key_issues:
        print("✅ API Key 配置正确")
        if verbose and api_key:
            masked = api_key[:12] + '*' * (len(api_key) - 16) + api_key[-4:]
            print(f"   密钥: {masked}")
            print(f"   长度: {len(api_key)} 字符")
    else:
        for level, msg in key_issues:
            icon = {"critical": "🔴", "error": "❌", "warning": "⚠️ "}.get(level, "")
            print(f"{icon} {level.upper()}: {msg}")
            if level in ["critical", "error"]:
                all_passed = False
    
    print()
    
    # 验证 FEISHU_APP_SECRET
    print("-" * 50)
    print("📌 FEISHU_APP_SECRET 检查:")
    print("-" * 50)
    
    secret_issues = validate_feishu_secret(feishu_secret)
    
    if not secret_issues:
        print("✅ App Secret 配置正确")
        if verbose and feishu_secret:
            masked = feishu_secret[:6] + '*' * (len(feishu_secret) - 10) + feishu_secret[-4:]
            print(f"   密钥: {masked}")
            print(f"   长度: {len(feishu_secret)} 字符")
    else:
        for level, msg in secret_issues:
            icon = {"critical": "🔴", "error": "❌", "warning": "⚠️ "}.get(level, "")
            print(f"{icon} {level.upper()}: {msg}")
            if level == "critical":
                all_passed = False
    
    print()
    
    # 可选：测试 API 连通性
    if check_api and api_key:
        print("-" * 50)
        print("📡 DeepSeek API 连通性测试:")
        print("-" * 50)
        print("   正在连接 https://api.deepseek.com/ ...")
        
        valid, msg = test_deepseek_api_key(api_key)
        print(f"   {msg}")
        
        if not valid:
            all_passed = False
    
    print()
    
    # 其他配置项检查
    print("-" * 50)
    print("📋 其他配置项:")
    print("-" * 50)
    
    other_vars = {
        "XIAOPAW_ENV": ("运行环境", lambda v: v in ['dev', 'production']),
        "MEMORY_DB_DSN": ("pgvector DSN", lambda v: v is not None),
        "AGENT_MEMORY_URL": ("远程记忆服务地址", lambda v: v is not None),
        "AGENT_MEMORY_API_KEY": ("远程记忆 API Key", lambda v: v is not None),
        "XIAOPAW_TEST_API_ENABLED": ("TestAPI 开关", lambda v: v in [True, False, None]),
    }
    optional_unset_hints = {
        "MEMORY_DB_DSN": "(未设置 - L21 向量记忆将不可用)",
        "AGENT_MEMORY_URL": "(未设置 - 远程长期记忆将不可用)",
        "AGENT_MEMORY_API_KEY": "(未设置 - 远程长期记忆将不可用)",
    }

    for var_name, (desc, validator) in other_vars.items():
        value = os.getenv(var_name, '')
        status = validator(value) if callable(validator) else bool(value)

        icon = "✅" if (status or var_name in optional_unset_hints and not value) else "⚠️ "

        if var_name in optional_unset_hints:
            display_value = optional_unset_hints[var_name] if not value else "已设置"
        elif value:
            display_value = str(value)
        else:
            display_value = "(默认值)"

        print(f"  {icon} {var_name}: {display_value}")

    # 可选：远程记忆服务（agent-memory-system）连通性探测
    memory_url = os.getenv("AGENT_MEMORY_URL", "")
    if check_api and memory_url:
        print()
        print("-" * 50)
        print("📡 远程记忆服务连通性测试:")
        print("-" * 50)
        valid, msg = test_agent_memory_service(memory_url, os.getenv("AGENT_MEMORY_API_KEY", ""))
        print(f"   {msg}")
        if not valid:
            all_passed = False
    
    print()
    print("=" * 50)
    
    if all_passed:
        print("🎉 所有关键检查通过！可以启动服务。")
        print()
        print("下一步操作：")
        print("  1. 启动服务: python xiaopaw/main.py")
        print("  2. 测试接口: curl http://127.0.0.1:9090/api/test/message ...")
        return 0
    else:
        print("⚠️  存在问题需要修复，请查看上方错误信息。")
        print()
        print("帮助文档：docs/deepseek-api-key-setup-guide.md")
        return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    
    verbose = "--verbose" in args or "-v" in args
    check_api = "--check-api" in args
    
    exit_code = main(verbose=verbose, check_api=check_api)
    sys.exit(exit_code)
