"""
Sidecar Manifest — 追踪 Agent 创建的文件，支持清理

记录 Agent 在运行过程中创建的所有 sidecar 文件，
任务完成后根据 manifest 统一清理，防止残留文件堆积。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class SidecarManifest:
    """
    追踪 Agent 创建的 sidecar 文件。

    用法:
        manifest = SidecarManifest(work_dir=".agent_context")
        manifest.track("runtime_brief.json")
        manifest.track("creative_output/video_001.mp4")
        # ... 任务完成 ...
        manifest.cleanup()  # 删除所有追踪的文件
    """

    MANIFEST_FILE = "manifest.json"

    def __init__(self, work_dir: str = ""):
        self.work_dir = Path(work_dir) if work_dir else Path.cwd() / ".agent_context"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._files: list[str] = []       # 相对路径
        self._created_dirs: list[str] = []

    # ─── 追踪 ─────────────────────────────────

    def track(self, file_path: str):
        """追踪一个文件"""
        self._files.append(file_path)

    def track_dir(self, dir_path: str):
        """追踪一个目录"""
        self._created_dirs.append(dir_path)

    def track_all(self, paths: list[str]):
        """批量追踪文件"""
        self._files.extend(paths)

    # ─── 持久化 ─────────────────────────────────

    def save(self):
        """保存 manifest 到磁盘"""
        manifest_path = self.work_dir / self.MANIFEST_FILE
        data = {
            "created_at": datetime.now().isoformat(),
            "files": self._files,
            "dirs": self._created_dirs,
        }
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> bool:
        """从磁盘加载 manifest"""
        manifest_path = self.work_dir / self.MANIFEST_FILE
        if not manifest_path.exists():
            return False
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._files = data.get("files", [])
            self._created_dirs = data.get("dirs", [])
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    # ─── 清理 ─────────────────────────────────

    def cleanup(self, keep_manifest: bool = False) -> dict:
        """
        清理所有追踪的文件和目录。
        返回 {deleted: int, failed: int, errors: list}。
        """
        result = {"deleted": 0, "failed": 0, "errors": []}

        # 先删除文件
        for rel_path in self._files:
            abs_path = self.work_dir / rel_path
            try:
                if abs_path.exists():
                    abs_path.unlink()
                    result["deleted"] += 1
            except Exception as e:
                result["failed"] += 1
                result["errors"].append(str(e))

        # 再删除空目录（反向删除，先子目录）
        for rel_path in reversed(sorted(self._created_dirs, key=len)):
            abs_path = self.work_dir / rel_path
            try:
                if abs_path.exists() and abs_path.is_dir():
                    # 只删除空目录
                    if not any(abs_path.iterdir()):
                        abs_path.rmdir()
            except Exception as e:
                result["errors"].append(str(e))

        # 删除 manifest 本身
        manifest_path = self.work_dir / self.MANIFEST_FILE
        if not keep_manifest and manifest_path.exists():
            try:
                manifest_path.unlink()
            except Exception:
                pass

        self._files.clear()
        self._created_dirs.clear()
        return result

    @property
    def file_count(self) -> int:
        return len(self._files)

    @property
    def total_tracked(self) -> int:
        return len(self._files) + len(self._created_dirs)
