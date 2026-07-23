# Snack Video Agent — 项目指南

## 项目概述

这是一个面向抖音千川信息流广告的 AI Agent，专为零食品类设计。
输入产品信息，自动生成短视频广告素材（脚本 + Wan2.2 视频 + 投放文案 + 人群定向）。

7 层管道架构：输入 → 模型 → 记忆 → 工具 → 上下文 → 执行 → 输出。

## 启动方式

```bash
pip install -r requirements.txt
python main.py
# → http://127.0.0.1:8000
```

## 环境变量

复制 .env.example 为 .env，填入你的 DashScope API Key：

```bash
DASHSCOPE_API_KEY=sk-xxx    # 阿里云 DashScope
AGENT_MODE=live             # demo=本地规则 / live=LLM+视频
LIVE_ENABLE_VIDEO=true      # 是否调用 Wan2.2 生成视频
OUTPUT_DIR=/data/outputs    # Railway 持久化成片目录
SITE_ACCESS_PASSWORD=xxx    # 公网访问密码，只放部署平台环境变量
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `main.py` | FastAPI 主入口，依赖注入 |
| `config.py` | 全局配置，从环境变量读取 |
| `layer6_execution/agent.py` | Agent 核心编排（ReAct + Controller Pipeline） |
| `layer4_tools/tools/wan22.py` | Wan2.2 视频生成工具 |
| `generate_video.py` | 独立的 10 秒图生视频诊断脚本（2 × 5s） |
| `add_voiceover.py` | TTS 口播 + 音视频合成 |
| `static/index.html` | 前端 SPA |

## 新增功能时注意

- Demo 和 Live 两套路径都要覆盖（`_demo_generate` 和 `_llm_generate`）
- 真实成片用 `_generate_10s_video`：商品主图 Base64 输入、2 × 5s I2V、ffmpeg 拼接、持久化和口播
- Live 模式必须配置 `SITE_ACCESS_PASSWORD`，`/health` 保持公开供 Railway 检查
- 记忆系统是 SQLite + ChromaDB 双存储，素材存档在 `data/` 目录
- 所有 API Key 必须从环境变量读取，不能硬编码
