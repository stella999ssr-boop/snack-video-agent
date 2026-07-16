# Snack Video Agent — Codex 启动提示词

## 初次使用（复制下面全部内容粘贴到 Codex）

---

我正在接手一个已完成的 Python 项目，请先了解它的整体架构和运行方式，然后帮我启动它。

## 项目信息

- 项目名：snack-video-agent（零食投流素材生成 Agent）
- GitHub：https://github.com/stella999ssr-boop/snack-video-agent
- 用途：输入零食产品信息，自动生成抖音千川广告素材（脚本 + Wan2.2 视频 + 投放文案 + 人群定向）

## 架构（7 层管道）

```
layer1_input      → FastAPI 路由、文件上传、产品输入
layer2_model      → LLM 模型层（System Prompt、千川标签字典）
layer3_memory     → 记忆系统（SQLite 结构化 + ChromaDB 向量检索）
layer4_tools      → 工具层（Wan2.2 视频生成、蝉妈妈数据采集、合规审核、质量评估）
layer5_context    → 上下文注入（Multica 模式：一进两写两清理）
layer6_execution  → Agent 核心编排（ReAct 循环 + Controller Pipeline）
layer7_output     → 输出/反馈/报告层
```

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `main.py` | FastAPI 入口，依赖注入 |
| `config.py` | 全局配置（环境变量驱动） |
| `layer6_execution/agent.py` | Agent 核心，ReAct 循环 + 多镜视频生成逻辑 |
| `layer4_tools/tools/wan22.py` | Wan2.2 T2V/I2V 工具封装 |
| `generate_video.py` | 独立 15s 多镜视频生成脚本（3段 × 5s + ffmpeg 拼接） |
| `add_voiceover.py` | TTS 口播 + 音视频合成 |
| `static/index.html` | 前端 SPA（素材生成/素材管理/效果反馈 三页） |

## 运行模式

- Demo 模式：本地规则生成脚本和文案，不调用任何 API。`AGENT_MODE=demo`
- Live 模式：调用通义千问 qwen-plus（LLM）+ 通义万相 Wan2.2（视频生成）。需要 API Key

## 环境变量

```
DASHSCOPE_API_KEY=sk-你的key    # 阿里云 DashScope
AGENT_MODE=demo                 # 或 live
LIVE_ENABLE_VIDEO=false         # live 模式下是否真的调 Wan2.2
PORT=8000
```

## 请你做的事

1. 先读 AGENTS.md 和 CLAUDE.md 了解项目约定
2. 检查 Python 环境和依赖是否就绪
3. 用 demo 模式启动服务
4. 告诉我浏览器打开什么地址

---

## 日常开发常用提示词

### 启动 & 调试
```
以 live 模式启动服务，开启视频生成
```
```
前端提交生成后报错，帮我排查后端日志
```
```
Wan2.2 返回了什么错误？看一下 DashScope API 的请求和响应
```

### 功能开发
```
在素材生成表单里加一个新字段"保质期"，同时在 demo 和 live 两套生成逻辑里都支持它
```
```
给前端加一个「一键复制全部文案」按钮，放在结果区域
```
```
我在 layer4_tools 下新增了一个工具 xxx.py，帮我把它注册到 ToolRegistry 并在 Agent 流程中调用
```

### 记忆系统
```
帮我查一下 ChromaDB 里存了哪些历史素材，按品类分组统计
```
```
素材存档时漏了某个字段，帮我补上，同时更新 creative_archive.py 和 schemas.py
```

### 提交代码
```
帮我提交代码到 GitHub，commit message 用中文
```

---

## 给 Codex 的全局约束（可选，放在对话开头）

```
你是一个 Python 后端 + FastAPI 开发者，正在维护一个 7 层架构的 AI Agent 项目。

核心规则：
1. 所有 API Key 必须从环境变量读取，绝不能硬编码
2. 新增功能要同时支持 demo 模式（本地规则）和 live 模式（LLM+API）
3. 修改 agent.py 时要小心 ReAct 循环的状态管理
4. 多镜视频生成走 _generate_multi_shot_video，不要用旧的单镜方法
5. 前端是原生 HTML 单文件，零构建依赖，不要引入 npm/webpack
6. 提交代码前确保 python main.py 能正常启动
```
