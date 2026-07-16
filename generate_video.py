"""
15s 多镜视频生成 + 拼接流水线
策略: Wan2.2 单次 5s × 3 段 → 交叉淡入淡出 → 合并为 15s → 叠加口播

核心让过渡自然:
  1. 3 段 prompt 共享视觉 DNA（灯光、色调、手持感）
  2. 过渡处用 dissolve（交叉淡入淡出 0.5s）
  3. 连续 TTS 口播贯穿全场，听觉不断则视觉切不显生硬
"""

import os
import time
import httpx
import tempfile
import subprocess

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

if not API_KEY:
    raise RuntimeError("请设置环境变量 DASHSCOPE_API_KEY")

BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
T2V_MODEL = "wan2.2-t2v-plus"

# ═══════════════════════════════════════════════════════
# Wan2.2 工具函数
# ═══════════════════════════════════════════════════════

client = httpx.Client(
    base_url=BASE_URL,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    },
    timeout=httpx.Timeout(300),
)


def submit_t2v(prompt: str, duration: int = 5, resolution: str = "720P") -> str:
    """提交文生视频任务，返回 task_id"""
    body = {
        "model": T2V_MODEL,
        "input": {"prompt": prompt, "negative_prompt": ""},
        "parameters": {"duration": duration, "resolution": resolution},
    }
    resp = client.post("/services/aigc/video-generation/video-synthesis", json=body)
    data = resp.json()
    if "code" in data and data["code"]:
        raise RuntimeError(f"DashScope 错误: {data}")
    task_id = data["output"]["task_id"]
    print(f"  [提交] task_id={task_id}  prompt={prompt[:60]}...")
    return task_id


def wait_task(task_id: str, max_wait: int = 180) -> str:
    """轮询等待，返回 video_url"""
    for _ in range(max_wait // 5):
        resp = client.get(f"/tasks/{task_id}")
        data = resp.json()
        status = data.get("output", {}).get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            out = data.get("output", {})
            results = out.get("results", {})
            url = results.get("video_url") if isinstance(results, dict) else None
            if not url:
                url = out.get("video_url")
            return url
        if status == "FAILED":
            raise RuntimeError(f"任务失败: {data.get('output', {}).get('message', '')}")
        print(f"  [等待] {task_id[:8]}... {status}")
        time.sleep(5)
    raise TimeoutError(f"任务超时: {task_id}")


def download_video(url: str, path: str):
    """下载视频到本地"""
    r = httpx.get(url, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    print(f"  [下载] {path} ({len(r.content) / 1024:.0f} KB)")


# ═══════════════════════════════════════════════════════
# 多镜脚本 → 3 段 Wan2.2 prompt
# ═══════════════════════════════════════════════════════

def build_multi_shot_prompts(
    product_name: str,
    selling_points: list[str],
    taste_tags: list[str],
    price: float,
    scene: str = "",
) -> list[dict]:
    """
    将 15 秒广告拆为 3 幕，每幕 5 秒。
    每段 prompt 共享视觉 DNA，结尾句承接下一段开头。
    """

    sp = "，".join(selling_points[:3])
    taste = "，".join(taste_tags)
    scene_text = scene or "追剧"

    # 共享视觉 DNA（三段都会包含的关键词）
    VISUAL_DNA = (
        "Vertical 9:16 smartphone video, 720p. "
        "Warm food lighting, natural color grading, appetizing food cinematography, "
        "handheld slight camera shake, cinematic depth of field. "
    )

    shots = [
        {
            "time": "0-5s",
            "label": "钩子开场",
            "script": f"这个{product_name}你们一定要试试，{sp}，不是那种普通零食",
            "wan22_prompt": (
                VISUAL_DNA
                + f"Opening shot: macro close-up of golden crispy {product_name} on rustic wooden table, "
                f"steam rising, texture detail visible. Camera slowly pushes in. "
                f"Warm amber tones, shallow depth of field on the snack. "
                f"Slight slow motion. 5 seconds."
            ),
        },
        {
            "time": "5-10s",
            "label": "产品展示",
            "script": f"{taste}的质感，蓬蓬松松咬下去特别酥。关键还是减油版，吃一整袋嘴里不腻",
            "wan22_prompt": (
                VISUAL_DNA
                + f"Continuation shot: someone picking up {product_name} with fingers, "
                f"bringing it to mouth, satisfying bite in slow motion, crumbs falling. "
                f"Golden light through window, natural food blogger POV. "
                f"Same warm color palette and depth of field as previous shot. "
                f"Texture and crunch emphasized. 5 seconds."
            ),
        },
        {
            "time": "10-15s",
            "label": "下单引导",
            "script": f"热量还不高，{scene_text}的时候拆一包太爽了。{price}元到手，左下角有链接，快去试试",
            "wan22_prompt": (
                VISUAL_DNA
                + f"Final shot: wide view of snack spread on table in cozy room, "
                f"product packaging visible, {scene_text} scene in background. "
                f"Warm inviting atmosphere, soft evening light. "
                f"Same handheld aesthetic and warm tones as preceding shots. "
                f"End with slight zoom out revealing full scene. 5 seconds."
            ),
        },
    ]

    return shots


# ═══════════════════════════════════════════════════════
# 视频拼接 + 口播合成
# ═══════════════════════════════════════════════════════

def concatenate_with_crossfade(
    video_paths: list[str],
    output_path: str,
    crossfade_duration: float = 0.4,
) -> str:
    """
    用 ffmpeg 拼接 3 段视频，交叉淡入淡出过渡。

    原理: 每两段之间 overlapped，用 fade filter 做 dissolve
    """
    if len(video_paths) < 2:
        # 单段视频，直接复制
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_paths[0], "-c", "copy", output_path],
            check=True, capture_output=True,
        )
        return output_path

    # 先获取每段视频的准确时长
    durations = []
    for v in video_paths:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", v],
            capture_output=True, text=True, check=True,
        )
        durations.append(float(result.stdout.strip()))

    if len(video_paths) == 3:
        # ffmpeg 3 段拼接待 crossfade
        cmd = [
            "ffmpeg", "-y",
            "-i", video_paths[0],
            "-i", video_paths[1],
            "-i", video_paths[2],
            "-filter_complex",
            (
                f"[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}:offset={durations[0] - crossfade_duration}[v01];"
                f"[v01][2:v]xfade=transition=fade:duration={crossfade_duration}:offset={durations[0] + durations[1] - 2 * crossfade_duration}[vout]"
            ),
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    else:
        # 2 段拼接
        cmd = [
            "ffmpeg", "-y",
            "-i", video_paths[0],
            "-i", video_paths[1],
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}:offset={durations[0] - crossfade_duration}[vout]",
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

    subprocess.run(cmd, check=True, capture_output=True)
    print(f"  [拼接] {len(video_paths)}段 → {output_path} (交叉淡入淡出 {crossfade_duration}s)")
    return output_path


def add_voiceover(video_path: str, script_lines: list[str], output_path: str):
    """
    生成连续 TTS 口播并叠加到拼接后的视频上。
    口播是贯穿全文的，视觉切时听觉不断 = 过渡自然。
    """
    full_script = " ".join(script_lines)

    # 生成 TTS 口播
    voice_path = video_path.replace(".mp4", "_voice.mp3")
    import subprocess as sp
    sp.run([
        "edge-tts",
        "--voice", "zh-CN-XiaoyiNeural",
        "--text", full_script,
        "--write-media", voice_path,
    ], check=True, capture_output=True)
    print(f"  [TTS] 口播已生成: {voice_path}")

    # 合并视频 + 音频
    sp.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", voice_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-map", "0:v:0",
        "-map", "1:a:0",
        output_path,
    ], check=True, capture_output=True)
    print(f"  [合成] 视频+口播 → {output_path}")


# ═══════════════════════════════════════════════════════
# 主流水线
# ═══════════════════════════════════════════════════════

def generate_15s_ad(
    product_name: str = "食验室厚厚奶酪玉米片",
    selling_points: list[str] = None,
    taste_tags: list[str] = None,
    price: float = 9.9,
    scene: str = "追剧",
    output_dir: str = "",
):
    """多镜 15s 广告生成主流程"""

    if selling_points is None:
        selling_points = ["奶酪味浓", "减油版", "蓬松酥脆"]
    if taste_tags is None:
        taste_tags = ["咸甜", "奶香"]
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(__file__), "output")

    os.makedirs(output_dir, exist_ok=True)

    # ── Step 1: 生成 3 镜脚本 ──
    print("\n══════ Step 1: 生成 3 镜脚本 ══════")
    shots = build_multi_shot_prompts(
        product_name, selling_points, taste_tags, price, scene
    )
    for s in shots:
        print(f"  [{s['label']}] {s['time']}: {s['script'][:40]}...")

    # ── Step 2: 并行提交 3 个 Wan2.2 任务 ──
    print("\n══════ Step 2: 提交 Wan2.2 任务（3 段并行）══════")
    task_ids = []
    for s in shots:
        tid = submit_t2v(s["wan22_prompt"])
        task_ids.append(tid)

    # ── Step 3: 等待全部完成 ──
    print("\n══════ Step 3: 等待视频生成 ══════")
    video_urls = []
    for i, tid in enumerate(task_ids):
        print(f"  等待第 {i+1}/3 段 ({shots[i]['label']})...")
        url = wait_task(tid)
        video_urls.append(url)
        print(f"  完成: {url[:60]}...")

    # ── Step 4: 下载 3 段视频 ──
    print("\n══════ Step 4: 下载视频 ══════")
    video_files = []
    for i, url in enumerate(video_urls):
        fname = os.path.join(output_dir, f"shot_{i+1}_{shots[i]['label']}.mp4")
        download_video(url, fname)
        video_files.append(fname)

    # ── Step 5: 交叉淡入淡出拼接 ──
    print("\n══════ Step 5: 拼接（交叉淡入淡出 0.4s）══════")
    merged_path = os.path.join(output_dir, "merged_15s.mp4")
    concatenate_with_crossfade(video_files, merged_path, crossfade_duration=0.4)

    # ── Step 6: 生成口播并合成 ──
    print("\n══════ Step 6: TTS 口播合成 ══════")
    script_lines = [s["script"] for s in shots]
    final_path = os.path.join(output_dir, "final_15s_ad.mp4")
    add_voiceover(merged_path, script_lines, final_path)

    print(f"\n{'='*50}")
    print(f"✅ 完成! 最终视频: {final_path}")
    print(f"{'='*50}")

    return final_path


# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    generate_15s_ad()
