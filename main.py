"""
零食投流素材生成 Agent — 主入口
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
import os

from config import settings
from layer1_input import router as layer1_router
from layer1_input import archive_router, strategy_router, feedback_router
from layer1_input.routes_archive import set_memory as archive_set_memory
from layer1_input.routes_strategy import set_memory as strategy_set_memory
from layer1_input.routes_feedback import set_deps as feedback_set_deps
from layer1_input.routes_upload import router as upload_router
from layer3_memory import create_memory_manager
from layer6_execution import CreativeAgent
from layer7_output import (
    CreativeAdLinker,
    ReportCollector,
    FeedbackWriter,
    QianchuanTokenManager,
)

# ─── 初始化各层 ─────────────────────────────────

memory_manager = create_memory_manager(
    sqlite_path=settings.SQLITE_PATH,
    chroma_path=settings.CHROMA_PATH,
)

agent = CreativeAgent(
    memory_manager=memory_manager,
    dashscope_api_key=settings.DASHSCOPE_API_KEY,
    demo_mode=(settings.AGENT_MODE == "demo"),
    enable_video=settings.LIVE_ENABLE_VIDEO,
)
print(f"[main] demo_mode={settings.AGENT_MODE == 'demo'}, enable_video={settings.LIVE_ENABLE_VIDEO}")

# ─── 反馈层组件 ─────────────────────────────────

token_manager = QianchuanTokenManager(db_path=settings.SQLITE_PATH)
linker = CreativeAdLinker(db_path=os.path.join(os.path.dirname(settings.SQLITE_PATH), "links.db"))
collector = ReportCollector(
    db_path=settings.SQLITE_PATH,
    token_manager=token_manager,
    linker=linker,
)
writer = FeedbackWriter(memory=memory_manager, collector=collector)

# ─── 依赖注入到路由 ─────────────────────────────────

from layer1_input.routes import set_agent
set_agent(agent)
archive_set_memory(memory_manager)
strategy_set_memory(memory_manager)
feedback_set_deps(linker, collector, writer, memory_manager)

# ─── 应用 ─────────────────────────────────

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="为零食品类生成抖音短视频广告素材（脚本+视频+文案+人群建议）",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    """对所有 HTML 响应禁用缓存"""
    response: Response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.include_router(layer1_router)
app.include_router(archive_router)
app.include_router(strategy_router)
app.include_router(feedback_router)
app.include_router(upload_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.VERSION,
        "mode": settings.AGENT_MODE,
        "video_enabled": settings.LIVE_ENABLE_VIDEO,
    }


# 挂载前端静态文件（必须放在所有 API 路由之后，避免拦截）
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    print(f"启动 {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"模式: {settings.AGENT_MODE}")
    print(f"地址: http://{settings.HOST}:{settings.PORT}")
    print(f"文档: http://{settings.HOST}:{settings.PORT}/docs")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
