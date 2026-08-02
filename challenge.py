"""每日推歌挑战文案管理。

文案以 JSON 列表持久化在插件数据目录（``plugin_data/<name>/challenges.json``），
便于 WebUI 上传/导出/编辑。每条结构：``{"text": str, "source": str}``。

顺序模式下：第 N 天（自 ``challenge_start_date`` 起）取 ``challenges[(N-1) % len]``。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from astrbot.api import logger

PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_PUSH_TXT = PLUGIN_DIR / "song_push.txt"

SOURCE_MANUAL = "manual"
SOURCE_IMPORT = "import"
SOURCE_AI = "ai"


class ChallengeManager:
    """读写挑战文案列表。文件读写串行化在调用方（main / web_api）层面已天然单线程（asyncio）。"""

    def __init__(self, data_file: Path):
        self.data_file = data_file

    def _read(self) -> list[dict]:
        if not self.data_file.is_file():
            return []
        try:
            with self.data_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("text")]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[challenge] 读取文案库失败，将视为空: {e}")
        return []

    def _write(self, items: list[dict]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with self.data_file.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    # ---- 查询 ----
    def list_all(self) -> list[dict]:
        """返回全部文案（带 1-based idx）。"""
        return [{"idx": i + 1, **item} for i, item in enumerate(self._read())]

    def count(self) -> int:
        return len(self._read())

    def get_by_day(self, day_number: int) -> Optional[dict]:
        """按天数（1-based）取文案，列表耗尽后循环。空列表返回 None。"""
        items = self._read()
        if not items:
            return None
        idx = (day_number - 1) % len(items)
        return {"idx": idx + 1, **items[idx]}

    def get_challenge_for_date(self, today: date, start_date: date) -> Optional[dict]:
        """根据起算日计算今天是第几天并取对应文案。"""
        if today < start_date:
            return None
        day_number = (today - start_date).days + 1
        item = self.get_by_day(day_number)
        if item is None:
            return None
        item["day_number"] = day_number
        return item

    # ---- 增删改 ----
    def add(self, text: str, source: str = SOURCE_MANUAL) -> dict:
        text = (text or "").strip()
        items = self._read()
        items.append({"text": text, "source": source})
        self._write(items)
        return {"idx": len(items), "text": text, "source": source}

    def update(self, idx: int, text: str) -> Optional[dict]:
        """更新 1-based idx 对应条目。"""
        items = self._read()
        pos = idx - 1
        if not (0 <= pos < len(items)):
            return None
        items[pos]["text"] = (text or "").strip()
        self._write(items)
        return {"idx": idx, **items[pos]}

    def delete(self, idx: int) -> bool:
        items = self._read()
        pos = idx - 1
        if not (0 <= pos < len(items)):
            return False
        items.pop(pos)
        self._write(items)
        return True

    # ---- 批量 ----
    def add_many(self, texts: list[str], source: str = SOURCE_IMPORT) -> int:
        """追加多条文案，返回新增条数（跳过空行）。"""
        cleaned = [(t or "").strip() for t in texts if (t or "").strip()]
        if not cleaned:
            return 0
        items = self._read()
        items.extend({"text": t, "source": source} for t in cleaned)
        self._write(items)
        return len(cleaned)

    def replace_all(self, texts: list[str], source: str = SOURCE_IMPORT) -> int:
        """用给定列表整体覆盖文案库，返回写入条数。"""
        cleaned = [(t or "").strip() for t in texts if (t or "").strip()]
        self._write([{"text": t, "source": source} for t in cleaned])
        return len(cleaned)

    def import_from_text(self, raw: str, source: str = SOURCE_IMPORT) -> int:
        """把多行文本导入为文案库（追加），返回新增条数。"""
        return self.add_many(raw.splitlines(), source=source)

    def export_text(self) -> str:
        """导出为多行纯文本（供下载 .txt）。"""
        return "\n".join(item["text"] for item in self._read())


# ---- 工具函数 ----
def parse_start_date(raw: str, default: str = "2026-04-13") -> date:
    """解析配置里的起算日字符串，非法时回落到默认。"""
    raw = (raw or "").strip() or default
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        logger.warning(f"[challenge] 起算日格式非法 '{raw}'，回落到 {default}")
        return datetime.strptime(default, "%Y-%m-%d").date()


def bootstrap_from_default_txt(manager: ChallengeManager) -> int:
    """若文案库为空，从随插件附带的 song_push.txt 导入初始文案。

    旧 song_push.txt 第一行是占位 "test today"，这里跳过它。
    返回导入条数。
    """
    if manager.count() > 0:
        return 0
    if not DEFAULT_PUSH_TXT.is_file():
        return 0
    raw = DEFAULT_PUSH_TXT.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines()]
    if lines and lines[0].strip().lower() in {"test today", "test", ""}:
        lines = lines[1:]
    return manager.add_many(lines, source=SOURCE_IMPORT)
