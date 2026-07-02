# 🍿 Snack Video Agent

> 零食品类 AI 投流素材工厂 — 输入产品信息，自动生成抖音短视频广告素材

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 它能做什么

这是一个面向**抖音千川信息流广告**的 AI Agent，专为零食品类设计。你只需要填写产品信息（名称、价格、卖点、口味），Agent 自动完成：

- 🧠 **创意策略分析** — 结合历史素材库和用户偏好，确定最优创意方向
- ✍️ **短视频脚本生成** — 分镜脚本 + 钩子文案 + 投放标题
- 🎬 **Wan2.2 视频生成** — 调用通义万相 T2V 模型生成竖屏广告视频
- 👥 **人群定向建议** — 基于千川标签库给出精准定向方案
- ✅ **质量评估 + 合规检测** — 自动评分、审核敏感词和违规内容
- 📊 **效果反馈闭环** — 关联千川广告数据，策略效果排行，持续优化

## Demo 效果

> 产品：「食验室厚厚奶酪玉米片」— 9.9 元 — 奶酪味/减油/追剧零食

生成的视频预览：
```
static/uploads/final_demo.mp4   2.0MB · 5秒 · 9:16 竖屏 · 720P · 已合成口播
```

> Wan2.2 T2V 生成 → edge-tts 女声口播 → moviepy 音视频合成

## 架构设计

```
snack-video-agent/
├── main.py                    # FastAPI 主入口
├── config.py                  # 全局配置
├── generate_video.py          # Wan2.2 视频生成脚本
├── add_voiceover.py           # TTS 口播 + 音视频合成
│
├── layer1_input/              # ① 输入层 — 路由、上传、产品解析
├── layer2_model/              # ② 模型层 — System Prompt、标签字典
├── layer3_memory/             # ③ 记忆层 — SQLite + ChromaDB 向量存储
├── layer4_tools/              # ④ 工具层 — Wan2.2、蝉妈妈、合规审核、质量评估
├── layer5_context/            # ⑤ 上下文层 — Multica 模式上下文注入
├── layer6_execution/          # ⑥ 执行层 — ReAct 循环 + Controller Pipeline
├── layer7_output/             # ⑦ 输出层 — 报告、广告关联、Token 管理
│
├── static/
│   ├── index.html             # 前端 SPA（三页：生成/管理/反馈）
│   └── preview.html           # 视频预览页
└── requirements.txt
```

### 工作流程

```
产品信息
  → ① 输入解析（类目级联、标签提取、图片上传）
  → ② LLM 分析（通义千问 qwen-plus）
  → ③ 记忆检索（同品类历史素材 + 策略效果）
  → ④ 视频生成（通义万相 Wan2.2 T2V，5秒竖屏）
  → ⑤ 质量评估 + 合规检测
  → ⑥ 素材存档（SQLite + ChromaDB）
  → ⑦ 输出 Creative Bundle（视频 + 脚本 + 标题 + 人群）
```

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 安装运行

```bash
# 1. 克隆项目
git clone https://github.com/stella999ssr-boop/snack-video-agent.git
cd snack-video-agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 Demo 模式（无需 API Key）
python main.py
# → 浏览器打开 http://127.0.0.1:8000
```

### Demo vs Live 模式

| 功能 | Demo 模式 | Live 模式 |
|------|----------|----------|
| 脚本/标题/人群 | ✅ 规则生成 | ✅ LLM 生成 |
| Wan2.2 视频 | ❌ | ✅ |
| TTS 口播 | ❌ | ❌（脚本独立运行） |
| 需要 API Key | 不需要 | 需要 |

### 开启 Live 模式

```bash
# Windows
set DASHSCOPE_API_KEY=sk-your-key
set AGENT_MODE=live
set LIVE_ENABLE_VIDEO=true

# Mac/Linux
export DASHSCOPE_API_KEY=sk-your-key
export AGENT_MODE=live
export LIVE_ENABLE_VIDEO=true

python main.py
```

> DashScope API Key 从 [阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/) 获取

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | DashScope API Key | - |
| `AGENT_MODE` | `demo` / `live` | `demo` |
| `LIVE_ENABLE_VIDEO` | live 模式下生成 Wan2.2 视频 | `false` |
| `HOST` | 服务监听地址 | `127.0.0.1` |
| `PORT` | 服务端口 | `8000` |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 前端界面 |
| `GET` | `/docs` | Swagger 文档 |
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/creative/generate` | 提交生成任务 |
| `GET` | `/api/v1/creative/status/{id}` | 查询任务进度 |
| `GET` | `/api/v1/creative/categories` | 获取类目树 |
| `GET` | `/api/v1/archive/all` | 素材列表 |
| `GET` | `/api/v1/archive/search` | 搜索素材 |
| `GET` | `/api/v1/archive/categories` | 素材类目统计 |
| `POST` | `/api/v1/feedback/link` | 素材↔千川广告关联 |
| `GET` | `/api/v1/feedback/performance/{id}` | 效果数据详情 |
| `GET` | `/api/v1/strategy/comparison` | 策略效果对比 |
| `GET` | `/api/v1/strategy/insight` | 策略洞察 |

## 前端页面

单页应用，三个标签页：

- **🪄 素材生成** — 产品表单 + 6 步进度条 + 结果展示（视频/脚本/标题/定向/质量/合规）
- **📂 素材管理** — 卡片网格 + 搜索筛选 + 详情弹窗
- **📊 效果反馈** — 千川广告关联 + 效果面板 + Chart.js 趋势图 + 策略排行

## 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | FastAPI + Uvicorn |
| AI 模型 | 通义千问 qwen-plus（LLM）+ 通义万相 Wan2.2（T2V） |
| 向量存储 | ChromaDB |
| 结构化存储 | SQLite |
| 音视频处理 | OpenCV + moviepy + edge-tts |
| 前端 | 原生 HTML + Tailwind CSS + Chart.js |
| 任务队列 | Celery（反馈数据异步采集） |

## License

MIT
