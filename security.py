"""Sensitive-data redaction for logs and API error responses."""

from __future__ import annotations

import os
import re
from typing import Any


_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9._~+/=-]{6,}", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"(?i)(Bearer\s+)[^'\"\r\n]+")
_KEY_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(DASHSCOPE_API_KEY\s*[=:]\s*)[^\s,;'\"}]+"
)


def redact_sensitive_data(value: Any) -> str:
    """Remove API keys and Authorization values from arbitrary error text."""
    text = str(value or "")

    raw_key = os.getenv("DASHSCOPE_API_KEY", "")
    for candidate in (raw_key, raw_key.strip()):
        if candidate:
            text = text.replace(candidate, "[已隐藏]")

    text = _BEARER_PATTERN.sub(r"\1[已隐藏]", text)
    text = _KEY_ASSIGNMENT_PATTERN.sub(r"\1[已隐藏]", text)
    text = _API_KEY_PATTERN.sub("sk-[已隐藏]", text)
    return text


def safe_error_message(error: Any) -> str:
    """Return a redacted, user-facing Chinese error without secret material."""
    raw = str(error or "")
    lowered = raw.lower()

    if "illegal header value" in lowered or (
        "authorization" in lowered and ("newline" in lowered or "\\n" in raw)
    ):
        return (
            "DashScope API Key 格式不正确，请检查 Railway Variables 中的 "
            "DASHSCOPE_API_KEY 是否包含空格或换行。"
        )
    if "timeout" in lowered or "timed out" in lowered:
        return "DashScope 请求超时，请稍后重试。"
    if any(marker in lowered for marker in ("unauthorized", "invalid api key", "invalidapikey", "401")):
        return "DashScope API Key 无效或已失效，请在 Railway Variables 中更新后重试。"

    sanitized = redact_sensitive_data(raw).strip()
    if not sanitized:
        return "生成失败，请稍后重试。"
    if sanitized.startswith(("DashScope ", "生成失败：", "生成失败，请")):
        return sanitized[:300]
    return f"生成失败：{sanitized[:300]}"
