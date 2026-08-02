"""卡片生成编排：把「取歌曲详情 → 下载封面/头像 → PIL 渲染」串起来。

对外只暴露 :func:`generate_song_card`，所有网络/IO 都走异步，
PIL 渲染（CPU 密集）用 ``asyncio.to_thread`` 放到线程池执行。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from astrbot.api import logger

import netease
from card_renderer import render_card

PLUGIN_DIR = Path(__file__).resolve().parent
FONT_PATH = PLUGIN_DIR / "Harmonyossans.ttf"


async def generate_song_card(
    song_id: int,
    *,
    recommender: Optional[str] = None,
    recommender_qq: Optional[str] = None,
    output_dir: Path,
) -> Optional[dict]:
    """生成一张歌曲卡片。

    Args:
        song_id: 网易云歌曲 id。
        recommender: 推荐人昵称（卡片底部显示）。
        recommender_qq: 推荐人 QQ 号（用于拉头像）。
        output_dir: PNG 输出目录，调用方应保证已存在。

    Returns:
        成功返回 ``{"path": <str>, "song": <详情dict>}``；
        取歌曲/封面失败返回 None。
    """
    try:
        song = await netease.fetch_song_detail(song_id)
        cover = await netease.download_cover(song["cover_url"])
    except Exception as e:  # noqa: BLE001 - 网络层有任意异常形态，统一降级
        logger.error(f"[musiccard] 获取歌曲信息失败 (id={song_id}): {e}")
        return None

    avatar = await netease.download_qq_avatar(recommender_qq) if recommender_qq else None

    output_path = output_dir / f"song_{song_id}_{uuid.uuid4().hex[:8]}.png"
    font = str(FONT_PATH) if FONT_PATH.is_file() else None

    # PIL 是 CPU 密集的同步库，丢到线程池避免阻塞事件循环。
    await asyncio.to_thread(
        render_card,
        song,
        cover,
        str(output_path),
        font,
        recommender,
        avatar,
    )
    return {"path": str(output_path), "song": song}
