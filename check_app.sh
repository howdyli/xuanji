#!/bin/bash
# 玄机 完整验证脚本

echo "=========================================="
echo "  玄机 应用验证"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

check_pass() {
    echo -e "${GREEN}✅ $1${NC}"
    PASS=$((PASS+1))
}

check_fail() {
    echo -e "${RED}❌ $1${NC}"
    FAIL=$((FAIL+1))
}

check_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 1. 检查 Python 版本
echo "1️⃣  检查 Python 环境"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
if [[ $(python3 -c "import sys; print(sys.version_info >= (3, 11))") == "True" ]]; then
    check_pass "Python 版本: $PYTHON_VERSION (>= 3.11)"
else
    check_fail "Python 版本: $PYTHON_VERSION (需要 >= 3.11)"
fi

# 2. 检查虚拟环境
echo ""
echo "2️⃣  检查虚拟环境"
if [ -d ".venv" ]; then
    check_pass "虚拟环境目录存在"
    if [ -f ".venv/bin/python3" ]; then
        check_pass "虚拟环境 Python 存在"
    else
        check_fail "虚拟环境 Python 不存在"
    fi
else
    check_fail "虚拟环境不存在"
fi

# 3. 检查核心依赖
echo ""
echo "3️⃣  检查核心依赖"
source .venv/bin/activate 2>/dev/null

DEPENDENCIES=("crewai" "pydantic" "aiohttp" "requests" "pyyaml" "lark-oapi")
for dep in "${DEPENDENCIES[@]}"; do
    if python3 -c "import $dep" 2>/dev/null; then
        check_pass "依赖: $dep"
    else
        check_fail "依赖: $dep (未安装)"
    fi
done

# 4. 检查环境变量
echo ""
echo "4️⃣  检查环境变量"
if [ -n "$DEEPSEEK_API_KEY" ]; then
    check_pass "DEEPSEEK_API_KEY 已设置 (${DEEPSEEK_API_KEY:0:15}...)"
else
    check_fail "DEEPSEEK_API_KEY 未设置"
fi

if [ -n "$XIAOPAW_ENV" ]; then
    check_pass "XIAOPAW_ENV=$XIAOPAW_ENV"
else
    check_warn "XIAOPAW_ENV 未设置（默认: dev）"
fi

# 5. 检查配置文件
echo ""
echo "5️⃣  检查配置文件"
if [ -f "config.yaml" ]; then
    check_pass "config.yaml 存在"
    
    # 检查 YAML 语法
    if python3 -c "import yaml; yaml.safe_load(open('config.yaml'))" 2>/dev/null; then
        check_pass "config.yaml 语法正确"
    else
        check_fail "config.yaml 语法错误"
    fi
else
    check_fail "config.yaml 不存在"
fi

if [ -f ".env" ]; then
    check_pass ".env 文件存在"
else
    check_warn ".env 文件不存在"
fi

# 6. 检查核心模块
echo ""
echo "6️⃣  检查核心模块"
MODULES=(
    "xiaopaw.llm.aliyun_llm:AliyunLLM"
    "xiaopaw.agents.main_crew:MemoryAwareCrew"
    "xiaopaw.agents.skill_crew:build_skill_crew"
    "xiaopaw.config.validator:load_config"
    "xiaopaw.hook_framework.registry:HookRegistry"
    "xiaopaw.runner:Runner"
    "xiaopaw.session.manager:SessionManager"
)

for module_info in "${MODULES[@]}"; do
    IFS=':' read -r module class <<< "$module_info"
    if python3 -c "from $module import $class" 2>/dev/null; then
        check_pass "模块: $module.$class"
    else
        check_fail "模块: $module.$class"
    fi
done

# 7. 检查 LLM 配置
echo ""
echo "7️⃣  检查 LLM 配置"
python3 << 'EOF'
try:
    from xiaopaw.llm.aliyun_llm import AliyunLLM
    llm = AliyunLLM(model='deepseek-v4-flash', region='deepseek')
    
    if 'api.deepseek.com' in llm.endpoint:
        print(f"✅ LLM 端点正确: {llm.endpoint}")
    else:
        print(f"❌ LLM 端点错误: {llm.endpoint}")
    
    if llm.api_key:
        print(f"✅ API Key 已配置: {llm.api_key[:15]}...")
    else:
        print("❌ API Key 未配置")
        
except Exception as e:
    print(f"❌ LLM 初始化失败: {e}")
EOF

# 8. 检查目录结构
echo ""
echo "8️⃣  检查目录结构"
DIRS=("xiaopaw" "tests" "docs" "workspace-init" "data")
for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        check_pass "目录: $dir/"
    else
        check_warn "目录: $dir/ (不存在)"
    fi
done

# 9. 检查测试
echo ""
echo "9️⃣  检查测试框架"
if command -v pytest &> /dev/null; then
    check_pass "pytest 已安装"
    
    # 快速运行一个测试
    if pytest tests/unit/hook_framework/test_hook_registry.py::TestDispatch::test_reg001_single_handler_dispatched -v 2>&1 | grep -q "PASSED"; then
        check_pass "测试框架工作正常"
    else
        check_warn "测试运行有问题"
    fi
else
    check_fail "pytest 未安装"
fi

# 10. 检查服务端口
echo ""
echo "🔟  检查服务端口"
if lsof -i :8090 2>/dev/null | grep -q LISTEN; then
    check_pass "指标服务运行中 (端口 8090)"
    if curl -s http://127.0.0.1:8090/metrics > /dev/null 2>&1; then
        check_pass "指标服务可访问"
    else
        check_warn "指标服务响应异常"
    fi
else
    check_warn "指标服务未运行 (端口 8090)"
fi

if lsof -i :9090 2>/dev/null | grep -q LISTEN; then
    check_pass "TestAPI 运行中 (端口 9090)"
else
    check_warn "TestAPI 未运行 (端口 9090)"
fi

# 总结
echo ""
echo "=========================================="
echo "  验证总结"
echo "=========================================="
echo ""
echo -e "${GREEN}通过: $PASS${NC}"
echo -e "${RED}失败: $FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 所有关键检查通过！应用配置正确！${NC}"
    echo ""
    echo "下一步操作："
    echo "  1. 启动服务: python -m xiaopaw.main"
    echo "  2. 运行测试: pytest tests/unit -v"
    echo "  3. 发送测试消息: curl -X POST http://127.0.0.1:9090/api/test/message ..."
    echo ""
    exit 0
else
    echo -e "${RED}⚠️  发现 $FAIL 个问题，请检查上面的错误信息${NC}"
    echo ""
    exit 1
fi
