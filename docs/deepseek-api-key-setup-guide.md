# DeepSeek API Key 获取与配置完整指南

> **更新日期**：2026-07-01
> **适用版本**：XiaoPaw v2（玄机）

---

## 📌 前言

由于之前代码中的 API Key 已泄露（`sk-5a78c12f1ad249828c88c11d60725512`），**必须立即更换新密钥**。

本指南将指导您：
1. ✅ 在 DeepSeek 控制台生成新的 API Key
2. ✅ 配置到 XiaoPaw 项目环境变量
3. ✅ 验证配置是否正确生效

---

## 第一步：获取新的 DeepSeek API Key

### 1.1 登录 DeepSeek 控制台

🔗 **访问地址**：https://platform.deepseek.com/

**操作步骤**：

1. 使用手机号或邮箱登录（支持微信扫码）
2. 进入控制台首页
3. 左侧菜单选择 **"API keys"**

### 1.2 生成新密钥

**操作界面**：

```
┌─────────────────────────────────────────────┐
│  API Keys                                    │
├─────────────────────────────────────────────┤
│                                              │
│  [+ Create new API key]                      │
│                                              │
│  ┌───────────────────────────────────┐      │
│  │ Key Name                          │      │
│  │ [xiaopaw-v2-production        ]   │      │
│  └───────────────────────────────────┘      │
│                                              │
│  Permissions:                                │
│  ○ Read-only    ● Full access (推荐)        │
│                                              │
│  IP Whitelist (可选):                        │
│  │ (留空 = 允许所有 IP)                     │
│  └──────────────────────────────────         │
│                                              │
│  [Create]  [Cancel]                          │
│                                              │
└─────────────────────────────────────────────┘
```

**建议设置**：
- **Key Name**：`xiaopaw-v2-production`（便于识别用途）
- **Permissions**：选择 `Full access`
- **IP Whitelist**：如需安全加固，填写服务器公网 IP（留空则允许所有 IP）

### 1.3 复制并保存新密钥

生成成功后，系统会显示 **完整的 API Key**（仅此一次可见）：

```
⚠️ 重要提示：请立即复制保存！关闭后无法再次查看完整密钥！

您的 API Key:
sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

（示例格式，实际为 48 位字母数字组合）
```

✅ **操作**：
1. 立即点击 "Copy" 按钮复制完整 Key
2. 安全地记录到密码管理器（如 1Password、LastPass）
3. **不要** 将其保存在明文文件、聊天工具或公开仓库中

---

## 第二步：配置到 XiaoPaw 环境变量

### 方式 A：使用交互式配置脚本（推荐新手）

```bash
cd /Users/howdy/work-source/xiaopaw-v2

# 赋予执行权限
chmod +x setup-env.sh

# 运行配置向导（会提示输入 API Key 和 Secret）
source setup-env.sh
```

**脚本功能**：
- 自动备份原 `.env` 文件
- 验证 API Key 格式（必须以 `sk-` 开头）
- 可选生成 Docker Compose 或 Systemd 配置
- 设置当前 shell 环境变量

---

### 方式 B：手动编辑 .env 文件

```bash
# 1. 打开 .env 文件
nano /Users/howdy/work-source/xiaopaw-v2/.env

# 2. 找到第 5 行，替换占位符：
DEEPSEEK_API_KEY=你的新API_Key_粘贴在这里

# 3. 同样修改第 9 行（飞书 Secret）：
FEISHU_APP_SECRET=你的飞书App_Secret_粘贴在这里

# 4. 保存退出（Ctrl+O, Enter, Ctrl+X）
```

**编辑后的 .env 示例**：

```env
# XiaoPaw v2 Environment Variables
# Updated: 2026-07-01

# === Required ===
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # ← 新 Key

# === Feishu (required for production) ===
FEISHU_APP_ID=cli_a93fd73285f8dcc8
FEISHU_APP_SECRET=your_new_feishu_secret_here        # ← 新 Secret

# === Environment ===
XIAOPAW_ENV=dev
```

---

### 方式 C：通过 Shell 环境变量（适合生产部署）

#### 方法 1：临时生效（当前终端会话）

```bash
export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxx"
export FEISHU_APP_SECRET="your_secret"
export XIAOPAW_ENV="production"

# 启动服务
python xiaopaw/main.py
```

#### 方法 2：永久生效（写入 shell 配置）

```bash
# 编辑 ~/.zshrc（macOS）或 ~/.bashrc（Linux）
echo '' >> ~/.zshrc
echo '# XiaoPaw v2' >> ~/.zshrc
echo 'export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxx"' >> ~/.zshrc
echo 'export FEISHU_APP_SECRET="your_secret"' >> ~/.zshrc

# 重新加载配置
source ~/.zshrc
```

#### 方法 3：Systemd 服务（Linux 生产环境）

创建 `/etc/systemd/system/xiaopaw.service`：

```ini
[Unit]
Description=XiaoPaw v2 AI Assistant
After=network.target postgresql.service

[Service]
Type=simple
User=xiaopaw
WorkingDirectory=/opt/xiaopaw
ExecStart=/usr/bin/python3 xiaopaw/main.py
EnvironmentFile=/etc/xiaopaw.env  # 从这里读取敏感信息

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

创建 `/etc/xiaopaw.env`：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
FEISHU_APP_SECRET=your_secret
XIAOPAW_ENV=production
MEMORY_DB_DSN=postgresql://xiaopaw:password@localhost:5432/xiaopaw
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now xiaopaw
sudo systemctl status xiaopaw
```

---

## 第三步：验证配置是否正确

### 3.1 检查 .env 文件内容

```bash
# 查看 DEEPSEEK_API_KEY 是否已设置
grep "^DEEPSEEK_API_KEY" .env

# 预期输出：
# DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx（非占位符文本）
```

### 3.2 测试 Python 能否读取

```bash
cd /Users/howdy/work-source/xiaopaw-v2

python3 -c "
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('DEEPSEEK_API_KEY', '')
secret = os.getenv('FEISHU_APP_SECRET', '')

print('=' * 40)
print('环境变量检查结果')
print('=' * 40)
print(f'DEEPSEEK_API_KEY: {\"✅ 已设置\" if key and \"YOUR_DEEP\" not in key else \"❌ 未设置/仍为占位符\"}')
if key:
    print(f'  格式验证: {\"✅ 正确\" if key.startswith(\"sk-\") else \"❌ 错误（应以 sk- 开头）\"}'  )
    print(f'  密钥长度: {len(key)} 字符')

print(f'FEISHU_APP_SECRET: {\"✅ 已设置\" if secret and \"YOUR_FEISHU\" not in secret else \"❌ 未设置/仍为占位符\"}')

print('=' * 40)
"
```

**预期输出**：

```
========================================
环境变量检查结果
========================================
DEEPSEEK_API_KEY: ✅ 已设置
  格式验证: ✅ 正确
  密钥长度: 48 字符
FEISHU_APP_SECRET: ✅ 已设置
========================================
```

### 3.3 启动服务并测试

```bash
cd /Users/howdy/work-source/xiaopaw-v2

# 启动 XiaoPaw 服务
python xiaopaw/main.py &

# 等待 10 秒让服务初始化
sleep 10

# 发送测试消息（需先启用 TestAPI）
export XIAOPAW_TEST_API_ENABLED=true
curl -X POST http://127.0.0.1:9090/api/test/message \
  -H "Content-Type: application/json" \
  -d '{"routing_key": "p2p:test", "text": "你好，请回复测试消息"}'
```

**预期响应**：
```json
{
  "status": "success",
  "message_id": "msg_xxx",
  "reply": "你好！我是玄机，很高兴为您服务...",
  "model": "deepseek-chat"
}
```

---

## 第四步：撤销旧密钥（关键！）

### 4.1 在 DeepSeek 控制台删除旧 Key

1. 回到 https://platform.deepseek.com/api_keys
2. 找到旧的 API Key（`sk-5a78c12f...5512`）
3. 点击右侧 "Delete" 或 "Revoke"
4. 确认删除

✅ **验证**：旧 Key 列表中不应再出现该密钥

### 4.2 清理 Git 历史（如果曾推送到远程）

```bash
# 安装 git-filter-repo（如果未安装）
brew install git-filter-repo  # macOS
# 或 pip install git-filter-repo

# 清理历史中的 .env 和 config.yaml
git filter-repo --invert-paths \
  --path .env \
  --path config.yaml \
  --force

# 强制推送到远程（⚠️ 会重写 Git 历史！）
git push origin main --force
```

⚠️ **重要提醒**：
- 如果是团队协作项目，**务必通知所有成员**
- 强制推送后需要所有成员 `rm -rf repo && git clone url` 重新克隆

---

## 🔒 安全最佳实践

### 1. 密钥轮换策略

| 操作 | 频率 | 说明 |
|------|------|------|
| 定期更换 | 每 90 天 | 即使未被泄露也应定期轮换 |
| 泄露后立即更换 | 即时 | 发现异常调用时 |
| 人员离职时更换 | 即时 | 防止前员工滥用 |

### 2. 最小权限原则

- **开发环境**：使用只读 API Key（如果 DeepSeek 支持）
- **生产环境**：限制 IP 白名单到服务器地址
- **监控用量**：设置预算告警（DeepSeek 控制台 → Usage → Alerts）

### 3. 审计日志

启用 Langfuse 后可追踪每次 LLM 调用：

```yaml
# config.yaml
observability:
  enable_langfuse: true
  langfuse_host: "http://localhost:3000"
  langfuse_public_key: "${LANGFUSE_PUBLIC_KEY}"
  langfuse_secret_key: "${LANGFUSE_SECRET_KEY}"
```

查看追踪数据：
```bash
docker logs langfuse-server | grep -i "api_key_usage"
```

---

## ❓ 常见问题排查

### Q1: 提示 "Invalid API Key"

**可能原因**：
- 复制时包含多余空格或换行符
- Key 不完整（应 48 字符）
- 旧 Key 已被撤销

**解决方案**：
```bash
# 检查是否有隐藏字符
cat -A .env | grep DEEPSEEK

# 应显示：
# DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx$
# （$ 表示行尾，不应有 ^M 或空格）
```

### Q2: 启动后报错 "Missing required env var"

**原因**：`.env` 文件未加载或格式错误

**解决**：
```bash
# 检查 python-dotenv 是否安装
pip show python-dotenv

# 手动加载测试
python -c "from dotenv import load_dotenv; print(load_dotenv())"
# 应返回 True
```

### Q3: Docker 容器内无法读取环境变量

**原因**：Docker Compose 默认读取 `.env.docker`，而非 `.env`

**解决**：
```bash
# 方案 A：重命名文件
cp .env .env.docker

# 方案 B：在 docker-compose.yml 中指定
environment:
  - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
env_file:
  - .env
```

---

## 📚 相关资源链接

- **DeepSeek 官方文档**：https://platform.deepseek.com/api-docs
- **API 价格表**：https://platform.deepseek.com/pricing
- **用量监控面板**：https://platform.deepseek.com/usage
- **飞书开放平台**：https://open.feishu.cn/app
- **Langfuse 文档**：https://langfuse.com/docs

---

## ✅ 配置完成检查清单

在开始使用前，请确认以下所有项已完成：

- [ ] 1. 已从 DeepSeek 控制台获取新的 API Key
- [ ] 2. 已将新 Key 配置到 `.env` 文件或环境变量
- [ ] 3. 已运行验证脚本确认配置正确
- [ ] 4. 已在 DeepSeek 控制台**撤销旧的 API Key**
- [ ] 5. 如有需要，已清理 Git 历史并强制推送
- [ ] 6. 已启动服务并通过 TestAPI 发送测试消息
- [ ] 7. 已设置 Langfuse 监控（生产环境推荐）

---

**完成以上所有步骤后，XiaoPaw v2 的 P0 安全修复任务即可视为圆满结束！** 🎉
