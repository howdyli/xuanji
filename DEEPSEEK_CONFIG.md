# DeepSeek 模型配置说明

## 快速开始

### 1. 设置环境变量

```bash
# 必需：DeepSeek API Key
export DEEPSEEK_API_KEY=your-api-key-here

# 可选：自定义 API 地址（默认使用官方地址）
# export DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 可选：调试模式（查看完整 LLM payload）
# export DEEPSEEK_DEBUG_PAYLOAD=true
```

### 2. 配置文件

复制并编辑配置文件：

```bash
cp config.yaml.example config.yaml
```

`config.yaml` 中的模型已默认配置为：
```yaml
agent:
  model: "deepseek-v4-flash"          # 主对话模型
  sub_agent_model: "deepseek-v4-flash" # Sub-Crew 模型
```

### 3. 验证配置

运行测试验证配置是否正确：

```bash
# 运行单元测试
pytest tests/unit -v

# 运行集成测试（需要 API Key）
pytest tests/integration -v

# 运行 E2E 测试（需要 API Key + Sandbox）
pytest tests/e2e -v -k "test_e2e_01"
```

## API 端点说明

### 主对话模型
- **端点**: `https://api.deepseek.com/v1/chat/completions`
- **模型**: `deepseek-v4-flash`
- **用途**: Main Agent 和 Sub-Crew 的主要对话模型

### 摘要模型
- **端点**: `https://api.deepseek.com/v1`
- **模型**: `deepseek-chat`
- **用途**: 记忆索引时的对话摘要生成

### Embedding 模型
- **端点**: 可配置（默认使用阿里云 `text-embedding-v3`）
- **用途**: 记忆向量化和语义搜索

> **注意**: DeepSeek 目前主要提供对话模型，embedding 功能仍需使用阿里云或其他服务。

## 环境变量优先级

代码中的环境变量读取顺序（高→低）：

1. `DEEPSEEK_API_KEY` - DeepSeek API Key（推荐）
2. `QWEN_API_KEY` - 向后兼容旧配置
3. `DASHSCOPE_API_KEY` - 向后兼容旧配置

Base URL 读取顺序：

1. `DEEPSEEK_BASE_URL` - 自定义 DeepSeek 端点
2. `QWEN_BASE_URL` - 向后兼容旧配置
3. 默认值 `https://api.deepseek.com/v1`

## 模型配置详情

### deepseek-v4-flash（主模型）
- **上下文窗口**: 131,072 tokens
- **特点**: 快速、经济，适合日常对话
- **温度**: 0.3（配置于代码中）

### deepseek-chat（摘要模型）
- **用途**: 生成对话摘要，用于记忆索引
- **最大 tokens**: 200

## 向后兼容

如果你之前使用 Qwen 模型，代码已做了向后兼容处理：

- 旧的环境变量（`QWEN_API_KEY`）仍然有效
- 只需设置新的 `DEEPSEEK_API_KEY` 即可切换
- 配置文件中的模型名需要手动更新（或使用新的 `config.yaml.example`）

## 常见问题

### Q: 可以使用其他 DeepSeek 模型吗？

A: 可以。修改 `config.yaml` 中的模型名称即可：
```yaml
agent:
  model: "deepseek-chat"  # 或其他可用的 DeepSeek 模型
```

### Q: 如何使用代理或自定义端点？

A: 设置 `DEEPSEEK_BASE_URL` 环境变量：
```bash
export DEEPSEEK_BASE_URL=https://your-proxy.com/v1
```

### Q: Embedding 功能怎么办？

A: 目前仍需使用阿里云的 embedding 服务。确保设置：
```bash
export QWEN_API_KEY=your-dashscope-api-key  # 用于 embedding
export DEEPSEEK_API_KEY=your-deepseek-api-key  # 用于对话
```

## 技术细节

### 代码修改清单

所有涉及模型调用的文件已更新：

- `xiaopaw/llm/aliyun_llm.py` - LLM 适配器
- `xiaopaw/agents/main_crew.py` - 主 Agent
- `xiaopaw/agents/skill_crew.py` - Sub-Crew
- `xiaopaw/memory/indexer.py` - 记忆索引
- `xiaopaw/skills/search_memory/scripts/search.py` - 记忆搜索
- `tests/e2e/conftest.py` - 测试配置

### API 兼容性

DeepSeek API 与 OpenAI API 完全兼容，因此：
- 使用 `openai` Python 包进行调用
- 使用标准的 chat completions 接口
- 支持 function calling 和 tool use

## 参考链接

- [DeepSeek API 文档](https://platform.deepseek.com/api-docs/)
- [DeepSeek 模型列表](https://platform.deepseek.com/)
- [OpenAI API 兼容说明](https://platform.deepseek.com/api-docs/zh-cn/)
