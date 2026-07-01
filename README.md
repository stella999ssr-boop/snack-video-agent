# 零食投流素材生成 Agent

> 为零食类商品自动生成抖音短视频广告素材（脚本 + Wan2.2 视频 + 人群定向 + 投放策略）

## 架构

7 层管道架构：

| 层 | 职责 |
|---|------|
| layer1_input | 用户输入（FastAPI 路由、文件上传、产品解析） |
| layer2_model | LLM 模型层（System Prompt、标签字典） |
| layer3_memory | 记忆系统（SQLite 结构化存储 + ChromaDB 向量检索） |
| layer4_tools | 工具层（Wan2.2 视频生成、蝉妈妈数据） |
| layer5_context | 上下文注入系统（Multica 模式） |
| layer6_execution | Agent 核心编排（Controller-Driven Pipeline） |
| layer7_output | 输出/反馈/报告层 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. Demo 模式（无需 API Key，本地规则生成）
python main.py
# → http://127.0.0.1:8000

# 3. Live 模式（DashScope LLM + Wan2.2 视频生成）
# Windows:
set DASHSCOPE_API_KEY=sk-your-key
set AGENT_MODE=live
set LIVE_ENABLE_VIDEO=true

# Mac/Linux:
export DASHSCOPE_API_KEY=sk-your-key
export AGENT_MODE=live
export LIVE_ENABLE_VIDEO=true

python main.py
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | DashScope API Key（通义千问 + 通义万相） | - |
| `AGENT_MODE` | `demo`（本地规则）/ `live`（LLM + 视频） | `demo` |
| `LIVE_ENABLE_VIDEO` | live 模式下是否生成 Wan2.2 视频 | `false` |
| `HOST` | 服务监听地址 | `127.0.0.1` |
| `PORT` | 服务端口 | `8000` |

## API 端点

| 路径 | 说明 |
|------|------|
| `GET /` | 前端页面 |
| `GET /docs` | Swagger API 文档 |
| `GET /health` | 健康检查 |
| `POST /api/v1/creative/generate` | 生成素材 |
| `GET /api/v1/creative/status/{request_id}` | 查询任务状态 |
| `GET /api/v1/archive/all` | 素材列表 |
| `GET /api/v1/archive/search` | 素材搜索 |
| `GET /api/v1/strategy/comparison` | 策略效果对比 |
| `POST /api/v1/feedback/link` | 素材↔广告关联 |

## 技术栈

- **后端**：Python 3.10+ / FastAPI / Uvicorn
- **LLM**：通义千问 qwen-plus（DashScope）
- **视频生成**：通义万相 Wan2.2（DashScope T2V API）
- **存储**：SQLite + ChromaDB
- **前端**：Tailwind CSS + Chart.js（单页应用）
