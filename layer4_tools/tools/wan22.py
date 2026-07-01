"""
Wan2.2 视频生成工具封装
通义万相 wan2.2-t2v / wan2.2-i2v via DashScope API

用法：
    tool = Wan22Tool(api_key="...")
    task_id = tool.t2v(prompt="...", duration=5)     # 文生视频
    task_id = tool.i2v(image_url="...", prompt="...") # 图生视频
    status, video_url = tool.wait(task_id)             # 轮询等待完成
"""

import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum

import httpx


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass
class Wan22Result:
    task_id: str
    status: TaskStatus
    video_url: Optional[str] = None
    error_message: Optional[str] = None


class Wan22Tool:
    """Wan2.2 视频生成工具"""

    BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

    # 支持的模型（按优先级排列，首个不可用时自动降级）
    T2V_MODELS = ["wan2.2-t2v-plus", "wanx-v1"]
    I2V_MODELS = ["wan2.2-i2v-plus", "wanx-i2v-v1"]

    # 支持的参数
    SUPPORTED_DURATIONS = {5, 8, 10}    # 秒
    SUPPORTED_RESOLUTIONS = {"720P", "1080P"}

    def __init__(self, api_key: str, timeout: int = 300):
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            timeout=httpx.Timeout(timeout),
        )

    # ─── 文生视频 ─────────────────────────────────

    def t2v(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720P",
        negative_prompt: Optional[str] = None,
    ) -> Wan22Result:
        """文生视频 — 提交异步任务，返回 task_id"""
        if duration not in self.SUPPORTED_DURATIONS:
            raise ValueError(f"不支持的时长 {duration}s，可选: {self.SUPPORTED_DURATIONS}")

        last_error = None
        for model in self.T2V_MODELS:
            try:
                body = {
                    "model": model,
                    "input": {
                        "prompt": prompt,
                        "negative_prompt": negative_prompt or "",
                    },
                    "parameters": {
                        "duration": duration,
                        "resolution": resolution,
                    },
                }
                resp = self._client.post("/services/aigc/video-generation/video-synthesis", json=body)
                data = resp.json()
                self._check_dashscope_error(data)
                task_id = data["output"]["task_id"]
                print(f"[Wan22] t2v 使用模型 {model}, task_id={task_id}")
                return Wan22Result(task_id=task_id, status=TaskStatus.PENDING)
            except Exception as e:
                print(f"[Wan22] t2v 模型 {model} 失败: {e}")
                last_error = e
                continue
        raise last_error or RuntimeError("所有 T2V 模型均不可用")

    # ─── 图生视频 ─────────────────────────────────

    def i2v(
        self,
        image_url: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720P",
    ) -> Wan22Result:
        """图生视频 — 以产品图作为首帧"""
        last_error = None
        for model in self.I2V_MODELS:
            try:
                body = {
                    "model": model,
                    "input": {
                        "prompt": prompt,
                        "first_frame_image": image_url,
                    },
                    "parameters": {
                        "duration": duration,
                        "resolution": resolution,
                    },
                }
                resp = self._client.post("/services/aigc/video-generation/video-synthesis", json=body)
                data = resp.json()
                self._check_dashscope_error(data)
                task_id = data["output"]["task_id"]
                print(f"[Wan22] i2v 使用模型 {model}, task_id={task_id}")
                return Wan22Result(task_id=task_id, status=TaskStatus.PENDING)
            except Exception as e:
                print(f"[Wan22] i2v 模型 {model} 失败: {e}")
                last_error = e
                continue
        raise last_error or RuntimeError("所有 I2V 模型均不可用")

    # ─── 任务状态查询 ─────────────────────────────────

    def query_task(self, task_id: str) -> Wan22Result:
        """查询异步任务状态"""
        resp = self._client.get(
            f"/tasks/{task_id}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-DashScope-Async": "enable",
            },
        )
        data = resp.json()
        self._check_dashscope_error(data)

        status = data.get("output", {}).get("task_status", "UNKNOWN")
        result = Wan22Result(task_id=task_id, status=TaskStatus(status))

        if status == "SUCCEEDED":
            # 尝试多种可能的返回路径
            output = data.get("output", {})
            results = output.get("results", {})
            if isinstance(results, dict):
                result.video_url = results.get("video_url") or results.get("video_urls", [None])[0]
            if not result.video_url:
                result.video_url = output.get("video_url")
            if not result.video_url:
                print(f"[Wan22] 任务完成但无法提取 video_url, output keys: {list(output.keys())}")
                result.error_message = f"无法提取 video_url, output={output}"
        elif status == "FAILED":
            result.error_message = data.get("output", {}).get("message", "未知错误")

        return result

    # ─── 阻塞等待 ─────────────────────────────────

    def wait(
        self,
        task_id: str,
        poll_interval: int = 5,
        max_wait: int = 300,
    ) -> Wan22Result:
        """轮询等待任务完成（阻塞）"""
        elapsed = 0
        while elapsed < max_wait:
            result = self.query_task(task_id)

            if result.status == TaskStatus.SUCCEEDED:
                return result
            if result.status == TaskStatus.FAILED:
                return result
            if result.status == TaskStatus.CANCELLED:
                return result

            time.sleep(poll_interval)
            elapsed += poll_interval

        return Wan22Result(
            task_id=task_id,
            status=TaskStatus.UNKNOWN,
            error_message=f"超时（{max_wait}s 内未完成）",
        )

    # ─── 工具方法 ─────────────────────────────────

    def _check_dashscope_error(self, data: dict):
        """检查 DashScope API 错误"""
        if "code" in data and data["code"] != "":
            raise RuntimeError(
                f"DashScope API 错误: code={data.get('code')}, message={data.get('message', 'unknown')}"
            )

    def health(self) -> bool:
        """检查 API Key 是否有效（轻量请求）"""
        try:
            resp = self._client.get(
                "/tasks/__health_check__",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            # 无效的 task_id 会返回错误但不是 401
            return resp.status_code != 401
        except Exception:
            return False
