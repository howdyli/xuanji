#!/bin/bash
# ============================================================
# XiaoPaw v2 环境变量配置脚本
# 用法：source setup-env.sh [api_key] [app_secret]
# 示例：source setup-env.sh sk-xxxxxxxxxxxx your_secret_here
# ============================================================

set -e

echo "🚀 XiaoPaw v2 环境变量配置向导"
echo "================================"

# 参数解析
DEEPSEEK_KEY="${1:-}"
FEISHU_SECRET="${2:-}"

if [ -z "$DEEPSEEK_KEY" ]; then
    echo ""
    echo "📝 请输入 DeepSeek API Key（从 https://platform.deepseek.com/ 获取）："
    read -r DEEPSEEK_KEY
fi

if [ -z "$FEISHU_SECRET" ]; then
    echo ""
    echo "📝 请输入飞书 App Secret（从 https://open.feishu.cn/app 获取）："
    read -r FEISHU_SECRET
fi

# 输入验证
if [ -z "$DEEPSEEK_KEY" ] || [ "$DEEPSEEK_KEY" = "YOUR_DEEPSEEK_API_KEY_HERE" ]; then
    echo "❌ 错误：DeepSeek API Key 不能为空"
    exit 1
fi

if [[ ! $DEEPSEEK_KEY =~ ^sk-[a-zA-Z0-9]{20,}$ ]]; then
    echo "⚠️  警告：API Key 格式可能不正确（应以 sk- 开头）"
    echo "   继续执行..."
fi

if [ -z "$FEISHU_SECRET" ] || [ "$FEISHU_SECRET" = "YOUR_FEISHU_APP_SECRET_HERE" ]; then
    echo "⚠️  警告：飞书 App Secret 为空，飞书功能将不可用"
fi

# 更新 .env 文件
ENV_FILE=".env"
BACKUP_FILE=".env.backup.$(date +%Y%m%d_%H%M%S)"

if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$BACKUP_FILE"
    echo "✅ 已备份原 .env 文件到 $BACKUP_FILE"
fi

cat > "$ENV_FILE" << EOF
# XiaoPaw v2 Environment Variables
# Auto-generated on $(date '+%Y-%m-%d %H:%M:%S')

# === Required ===
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}

# === Feishu (required for production) ===
FEISHU_APP_ID=cli_a93fd73285f8dcc8                  # 飞书应用 App ID
FEISHU_APP_SECRET=${FEISHU_SECRET}

# === Environment ===
XIAOPAW_ENV=dev                        # dev | production

# === pgvector (optional, for memory search) ===
# MEMORY_DB_DSN=postgresql://xiaopaw:xiaopaw@localhost:5432/xiaopaw

# === Langfuse (optional, for observability) ===
# TRACE_TO_LANGFUSE=true
# XIAOPAW_LANGFUSE_PUBLIC_KEY=pk-lf-...
# XIAOPAW_LANGFUSE_SECRET_KEY=sk-lf-...
# XIAOPAW_LANGFUSE_BASE_URL=http://localhost:3000

# === TestAPI (dev mode only) ===
# XIAOPAW_TEST_API_ENABLED=true
# XIAOPAW_TEST_API_TOKEN=your-dev-token
EOF

echo "✅ 已更新 .env 文件"

# 设置当前 shell 环境变量
export DEEPSEEK_API_KEY="$DEEPSEEK_KEY"
export FEISHU_APP_SECRET="$FEISHU_SECRET"
export XIAOPAW_ENV="dev"

echo ""
echo "================================"
echo "✅ 环境变量配置完成！"
echo ""
echo "📋 当前配置："
echo "  • DEEPSEEK_API_KEY: ${DEEPSEEK_KEY:0:12}...（已隐藏完整密钥）"
echo "  • FEISHU_APP_SECRET: $(if [ -n "$FEISHU_SECRET" ]; then echo "${FEISHU_SECRET:0:6}..."; else echo "(未设置)"; fi)"
echo "  • XIAOPAW_ENV: dev"
echo ""

# 可选：生成 systemd 环境文件或 docker-compose .env
echo "🔧 是否要生成其他配置格式？"
echo "  [1] Docker Compose (.env.docker)"
echo "  [2] Systemd 环境 (/etc/xiaopaw.env)"
echo "  [3] 跳过"
read -r CHOICE

case $CHOICE in
    1)
        cat > ".env.docker" << DOCKER_EOF
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
FEISHU_APP_ID=cli_a93fd73285f8dcc8
FEISHU_APP_SECRET=${FEISHU_SECRET}
XIAOPAW_ENV=production
DOCKER_EOF
        echo "✅ 已生成 Docker Compose 配置文件：.env.docker"
        ;;
    2)
        if [ "$EUID" -ne 0 ]; then
            echo "⚠️  需要 root 权限写入 /etc/ 目录，请使用 sudo 运行"
        else
            sudo tee /etc/xiaopaw.env > /dev/null << SYSTEMD_EOF
DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
FEISHU_APP_SECRET=${FEISHU_SECRET}
XIAOPAW_ENV=production
SYSTEMD_EOF
            echo "✅ 已写入 Systemd 环境文件：/etc/xiaopaw.env"
        fi
        ;;
    3|*)
        echo "⏭️  跳过"
        ;;
esac

echo ""
echo "🎉 下一步操作："
echo "  1. 启动服务：python xiaopaw/main.py 或 docker-compose up"
echo "  2. 测试 API：curl http://127.0.0.1:9090/api/test/message ..."
echo "  3. 查看日志：tail -f data/logs/*.log"
echo ""
