"""
10 秒双镜图生视频诊断脚本。

主站生成链路位于 layer6_execution/agent.py。这个脚本用于在部署前单独验证：
商品主图 → 两个 5 秒 Wan2.2 I2V 任务 → 10 秒竖屏 MP4。
"""

import argparse
import base64
import mimetypes
import os
import shutil
import subprocess
import tempfile

import httpx

from layer4_tools.tools.wan22 import TaskStatus, Wan22Tool


def image_to_data_url(image_path: str) -> str:
    path = os.path.abspath(image_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到商品主图: {path}")
    if os.path.getsize(path) > 10 * 1024 * 1024:
        raise ValueError("Wan2.2 商品主图不能超过 10MB")
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/bmp"}:
        raise ValueError("商品主图仅支持 JPG、PNG、WebP 或 BMP")
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_prompts(product_name: str, scene: str) -> list[str]:
    visual_dna = (
        "Vertical 9:16 smartphone food advertisement, 720p, warm natural lighting, "
        "appetizing detail, subtle handheld movement, cinematic depth of field. "
        "Use the uploaded product package as the exact first frame. Preserve the logo, "
        "colors, typography and package shape; do not alter packaging text. "
    )
    return [
        visual_dna
        + f"Opening shot: keep the {product_name} package readable while the camera slowly "
        "pushes in and reveals the snack texture beside it. 5 seconds.",
        visual_dna
        + f"Conversion shot: show the {product_name} package in a cozy {scene} setting, "
        "include a natural hand interaction, and end on a clean hero frame with room for CTA. "
        "5 seconds.",
    ]


def concat_exact_10s(video_paths: list[str], output_path: str):
    concat_filter = (
        "[0:v]fps=25,scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v0];"
        "[1:v]fps=25,scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v1];"
        "[v0][v1]concat=n=2:v=1:a=0,trim=duration=10,setpts=PTS-STARTPTS[vout]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_paths[0], "-i", video_paths[1],
            "-filter_complex", concat_filter, "-map", "[vout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path,
        ],
        check=True,
        capture_output=True,
    )


def generate_10s_ad(
    image_path: str,
    product_name: str,
    scene: str = "追剧",
    output_path: str = "output/final_10s_ad.mp4",
) -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("请先设置环境变量 DASHSCOPE_API_KEY")

    tool = Wan22Tool(api_key=api_key)
    image_input = image_to_data_url(image_path)
    prompts = build_prompts(product_name, scene)
    tasks = [
        tool.i2v(image_url=image_input, prompt=prompt, duration=5, resolution="720P")
        for prompt in prompts
    ]

    urls = []
    for index, task in enumerate(tasks):
        result = tool.wait(task.task_id, max_wait=600)
        if result.status != TaskStatus.SUCCEEDED or not result.video_url:
            raise RuntimeError(
                f"第 {index + 1} 镜生成失败: {result.error_message or result.status.value}"
            )
        urls.append(result.video_url)

    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="snack_10s_")
    try:
        video_paths = []
        for index, url in enumerate(urls):
            response = httpx.get(url, timeout=180, follow_redirects=True)
            response.raise_for_status()
            shot_path = os.path.join(tmpdir, f"shot_{index + 1}.mp4")
            with open(shot_path, "wb") as video_file:
                video_file.write(response.content)
            video_paths.append(shot_path)
        concat_exact_10s(video_paths, output_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="生成一条 10 秒真实商品图广告")
    parser.add_argument("--image", required=True, help="本地商品主图路径")
    parser.add_argument("--product", required=True, help="商品名称")
    parser.add_argument("--scene", default="追剧", help="消费场景")
    parser.add_argument("--output", default="output/final_10s_ad.mp4", help="输出 MP4 路径")
    args = parser.parse_args()
    result = generate_10s_ad(args.image, args.product, args.scene, args.output)
    print(f"完成: {result}")


if __name__ == "__main__":
    main()
