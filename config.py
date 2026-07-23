"""
全局配置
"""

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def read_env_bool(name: str, default: bool = False) -> bool:
    """读取部署平台布尔变量，清理粘贴产生的空格/换行并拒绝拼写错误。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{name} 配置无效，请使用 true/false、1/0、yes/no 或 on/off"
    )


class Settings:
    PROJECT_NAME = "零食投流素材生成 Agent"
    VERSION = "0.3.0"

    # DashScope (通义千问 + 通义万相)
    # 部署平台粘贴变量时可能意外带入换行；统一清理首尾空白。
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()

    # Agent 模式: demo=本地规则生成(无需API), live=调用DashScope LLM
    AGENT_MODE = os.getenv("AGENT_MODE", "demo").strip().lower()
    if AGENT_MODE not in {"demo", "live"}:
        raise ValueError("AGENT_MODE 配置无效，请使用 demo 或 live")

    # Live 模式下是否生成视频（Wan2.2 调用耗时且产生费用，首次测试建议关闭）
    LIVE_ENABLE_VIDEO = read_env_bool("LIVE_ENABLE_VIDEO", default=False)

    # 数据库路径
    SQLITE_PATH = os.getenv("SQLITE_PATH", "./data/snack_agent.db")
    CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./static/uploads")
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./static/outputs")

    # 公开部署的访问保护；密码只保存在部署平台环境变量中
    SITE_ACCESS_PASSWORD = os.getenv("SITE_ACCESS_PASSWORD", "")

    # 服务
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "8000"))


settings = Settings()
