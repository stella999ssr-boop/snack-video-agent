"""
全局配置
"""

import os


class Settings:
    PROJECT_NAME = "零食投流素材生成 Agent"
    VERSION = "0.2.0"

    # DashScope (通义千问 + 通义万相)
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

    # Agent 模式: demo=本地规则生成(无需API), live=调用DashScope LLM
    AGENT_MODE = os.getenv("AGENT_MODE", "demo")

    # Live 模式下是否生成视频（Wan2.2 调用耗时且产生费用，首次测试建议关闭）
    LIVE_ENABLE_VIDEO = os.getenv("LIVE_ENABLE_VIDEO", "false").lower() in ("1", "true", "yes")

    # 数据库路径
    SQLITE_PATH = os.getenv("SQLITE_PATH", "./data/snack_agent.db")
    CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")

    # 服务
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))


settings = Settings()
