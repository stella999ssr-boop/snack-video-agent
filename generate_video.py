"""
直接调用 Wan2.2 T2V 生成食验室奶酪玉米片短视频
"""

import time
import httpx

import os
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

# ─── 英文 Prompt（基于用户 4 镜脚本翻译 + 压缩为 10s）───
PROMPT = (
    "Vertical 9:16 smartphone video, 720p. "
    "Natural warm sunlight, iPhone handheld slight camera shake, "
    "real wooden desktop surface, food blogger review aesthetic. "
    "Overhead shot: bright yellow inflated snack bag with orange text design, "
    "golden-orange cheese corn chips pouring into white ceramic plate, "
    "piling up, cheese powder glistening with warm orange luster. "
    "Cut to close-up: finger snaps a chip revealing porous airy texture, crumbs scattering. "
    "Quick cut to product bag centered on desk, chips scattered around. "
    "Continuous warm food lighting, appetizing natural color grading."
)

client = httpx.Client(
    base_url=BASE_URL,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    },
    timeout=httpx.Timeout(120),
)

print("=" * 60)
print("提交 Wan2.2 T2V 任务...")
print(f"Prompt 长度: {len(PROMPT)} 字符")
print(f"时长: 10s | 分辨率: 720P | 比例: 9:16")
print("=" * 60)

# 提交任务
resp = client.post(
    "/services/aigc/video-generation/video-synthesis",
    json={
        "model": "wan2.2-t2v-plus",
        "input": {
            "prompt": PROMPT,
            "negative_prompt": "blurry, distorted, low quality, watermark, text overlay, ugly, dark",
        },
        "parameters": {
            "duration": 5,
            "resolution": "720P",
        },
    },
)

data = resp.json()
print(f"响应: {resp.status_code}")
if "error" in data or data.get("code"):
    print(f"错误: {data}")
    exit(1)

task_id = data["output"]["task_id"]
print(f"任务已提交! task_id = {task_id}")
print(f"状态: {data['output']['task_status']}")
print()

# 轮询等待
print("等待视频生成（通常需要 3-8 分钟）...")
for i in range(60):
    time.sleep(10)
    status_resp = client.get(f"/tasks/{task_id}")
    status_data = status_resp.json()
    status = status_data.get("output", {}).get("task_status", "UNKNOWN")
    elapsed = (i + 1) * 10
    print(f"  [{elapsed}s] {status}")

    if status == "SUCCEEDED":
        video_url = status_data["output"].get("video_url", "")
        print()
        print("=" * 60)
        print("视频生成成功!")
        print(f"URL: {video_url}")
        print("=" * 60)
        break
    elif status == "FAILED":
        print(f"失败: {status_data.get('output', {}).get('message', status_data)}")
        break

client.close()
