"""
Marker Block 管理器

管理上下文文件中的注入块：
  <!-- AGENT:START:block_name -->
  ...注入内容...
  <!-- AGENT:END:block_name -->

写之前先清理旧块，只动标记之间的内容，不动用户手写的内容。
"""

import re
from pathlib import Path
from typing import Optional

MARKER_START = r"<!--\s*AGENT:START:(\w+)\s*-->"
MARKER_END = r"<!--\s*AGENT:END:\1\s*-->"


class MarkerManager:
    """管理单个上下文文件中的标记注入块"""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._original_content = ""

    # ─── 读取 ─────────────────────────────────

    def read(self) -> str:
        """读取文件内容"""
        if self.file_path.exists():
            return self.file_path.read_text(encoding="utf-8")
        return ""

    # ─── 清理 ─────────────────────────────────

    def cleanup(self) -> int:
        """
        清理文件中所有注入块（标记及内容）。
        返回清理的块数量。
        """
        content = self.read()
        if not content:
            return 0

        pattern = re.compile(
            r"<!--\s*AGENT:START:\w+\s*-->.*?<!--\s*AGENT:END:\w+\s*-->\n?",
            re.DOTALL,
        )

        cleaned, count = pattern.subn("", content)
        if count > 0:
            # 清理多余空行
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            self.file_path.write_text(cleaned, encoding="utf-8")
        return count

    # ─── 注入 ─────────────────────────────────

    def inject(self, block_name: str, content: str) -> bool:
        """
        向文件注入一个标记块。
        如果 block_name 已存在，替换旧内容；否则追加到文件末尾。

        标记格式：
          <!-- AGENT:START:block_name -->
          content
          <!-- AGENT:END:block_name -->
        """
        marker = self._make_marker(block_name, content)
        existing = self.read()

        # 如果块已存在 → 替换
        pattern = re.compile(
            rf"<!--\s*AGENT:START:{re.escape(block_name)}\s*-->.*?<!--\s*AGENT:END:{re.escape(block_name)}\s*-->",
            re.DOTALL,
        )

        if pattern.search(existing):
            new_content = pattern.sub(marker, existing)
        else:
            # 追加到文件末尾
            if existing and not existing.endswith("\n"):
                existing += "\n"
            new_content = existing + "\n" + marker + "\n"

        self.file_path.write_text(new_content, encoding="utf-8")
        return True

    def remove_block(self, block_name: str) -> bool:
        """移除指定名称的注入块"""
        content = self.read()
        pattern = re.compile(
            rf"<!--\s*AGENT:START:{re.escape(block_name)}\s*-->.*?<!--\s*AGENT:END:{re.escape(block_name)}\s*-->\n?",
            re.DOTALL,
        )
        new_content = pattern.sub("", content)
        if new_content != content:
            self.file_path.write_text(new_content, encoding="utf-8")
            return True
        return False

    # ─── 查询 ─────────────────────────────────

    def list_blocks(self) -> list[str]:
        """列出文件中所有注入块名称"""
        content = self.read()
        return re.findall(r"<!--\s*AGENT:START:(\w+)\s*-->", content)

    def get_block(self, block_name: str) -> Optional[str]:
        """获取指定注入块的内容"""
        content = self.read()
        pattern = re.compile(
            rf"<!--\s*AGENT:START:{re.escape(block_name)}\s*-->\n?(.*?)\n?<!--\s*AGENT:END:{re.escape(block_name)}\s*-->",
            re.DOTALL,
        )
        match = pattern.search(content)
        return match.group(1).strip() if match else None

    # ─── 工具 ─────────────────────────────────

    @staticmethod
    def _make_marker(block_name: str, content: str) -> str:
        return (
            f"<!-- AGENT:START:{block_name} -->\n"
            f"{content.strip()}\n"
            f"<!-- AGENT:END:{block_name} -->"
        )


def cleanup_marker_blocks(file_paths: list[str]) -> dict[str, int]:
    """
    批量清理多个文件中的注入块。
    返回 {file_path: cleaned_count}。
    """
    result = {}
    for fp in file_paths:
        mgr = MarkerManager(fp)
        count = mgr.cleanup()
        if count > 0:
            result[fp] = count
    return result
