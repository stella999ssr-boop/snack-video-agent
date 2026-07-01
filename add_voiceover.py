"""
简易版：edge-tts 生成口播 + 合成视频
"""

import subprocess
import os
import httpx

VOICEOVER = "这个奶酪玉米片你们一定要试试，奶酪味巨浓，真的超好吃！"

OUT_DIR = "C:/Users/施佳佳/snack-ad-agent/output"
os.makedirs(OUT_DIR, exist_ok=True)
AUDIO_FILE = os.path.join(OUT_DIR, "voiceover.mp3")
VIDEO_URL = "https://dashscope-7c2c.oss-cn-shanghai.aliyuncs.com/1d/b6/20260613/89419ad1/dcfb7fee-30ea-4f7e-b858-75b44091eae5.mp4?Expires=1781432316&OSSAccessKeyId=LTAI5tPxpiCM2hjmWrFXrym1&Signature=e1MeUtqs8BoTLnNBvhdJ2Q8AjZc%3D"
VIDEO_FILE = os.path.join(OUT_DIR, "original_video.mp4")
OUTPUT_VIDEO = os.path.join(OUT_DIR, "final_with_voiceover.mp4")

# Step 1: TTS
print("Step 1: edge-tts 生成口播...")
result = subprocess.run([
    "edge-tts",
    "--voice", "zh-CN-XiaoyiNeural",
    "--text", VOICEOVER,
    "--write-media", AUDIO_FILE,
], capture_output=True, text=True, timeout=30)
if result.returncode != 0:
    print(f"失败: {result.stderr}")
    exit(1)
print(f"音频: {AUDIO_FILE} ({os.path.getsize(AUDIO_FILE)} bytes)")

# Step 2: Download video
print("Step 2: 下载原视频...")
r = httpx.get(VIDEO_URL, timeout=120)
with open(VIDEO_FILE, "wb") as f:
    f.write(r.content)
print(f"视频: {VIDEO_FILE} ({len(r.content)} bytes)")

# Step 3: Merge with ffmpeg (or just keep audio file)
print("Step 3: 检查 ffmpeg...")
ffmpeg_check = subprocess.run(["where", "ffmpeg"], capture_output=True)
if ffmpeg_check.returncode != 0:
    print("ffmpeg 未安装。音频已生成，视频文件也已下载。")
    print(f"音频: {AUDIO_FILE}")
    print(f"视频: {VIDEO_FILE}")
    print("请手动用剪映/CapCut 合成，或安装 ffmpeg: winget install ffmpeg")
else:
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", VIDEO_FILE,
        "-i", AUDIO_FILE,
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        "-map", "0:v:0", "-map", "1:a:0",
        OUTPUT_VIDEO,
    ], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        print(f"合成完成: {OUTPUT_VIDEO} ({os.path.getsize(OUTPUT_VIDEO)} bytes)")
    else:
        print(f"ffmpeg 失败: {result.stderr}")
