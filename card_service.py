"""卡片生成编排：把「取详情 → 下载封面/头像 → PIL 渲染」串起来。

对外只暴露 :func:`generate_share_card`，所有网络/IO 都走异步，
PIL 渲染（CPU 密集）用 ``asyncio.to_thread`` 放到线程池执行。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from astrbot.api import logger

import platforms
from imagecreate.card_renderer import render_album_card, render_card

PLUGIN_DIR = Path(__file__).resolve().parent


async def generate_share_card(
    platform: str,
    resource_id: str,
    *,
    recommender: Optional[str] = None,
    recommender_qq: Optional[str] = None,
    output_dir: Path,
) -> Optional[dict]:
    """生成一张分享卡片。

    Args:
        platform: 平台标识（netease / bilibili / qqmusic / kugou）。
        resource_id: 平台资源 id（网易云歌曲 id / B站 BV号 / QQ音乐 songmid / 酷狗 hash）。
        recommender: 推荐人昵称（卡片底部显示）。
        recommender_qq: 推荐人 QQ 号（用于拉头像）。
        output_dir: PNG 输出目录，调用方应保证已存在。

    Returns:
        成功返回 ``{"path": <str>, "song": <详情dict>}``；
        取详情/封面失败返回 None。
    """
    try:
        detail = await platforms.fetch_detail(platform, resource_id)
        cover = await platforms.download_cover(platform, detail["cover_url"])
    except Exception as e:  # noqa: BLE001 - 网络层有任意异常形态，统一降级
        logger.info(f"[musiccard] 获取分享信息失败 (platform={platform} id={resource_id}): {e}")
        return None

    avatar = await platforms.download_qq_avatar(recommender_qq) if recommender_qq else None

    output_path = output_dir / f"share_{platform}_{resource_id[:16]}_{uuid.uuid4().hex[:8]}.png"
    font = None  # 让 card_renderer._find_font 自行探测同目录字体

    # PIL 是 CPU 密集的同步库，丢到线程池避免阻塞事件循环。
    # 带曲目列表的详情（专辑）走专辑卡片渲染器。
    renderer = render_album_card if detail.get("tracks") else render_card
    logger.info(f"[musiccard] 开始渲染卡片：{detail.get('name','?')} (platform={platform} id={resource_id})")
    await asyncio.to_thread(
        renderer,
        detail,
        cover,
        str(output_path),
        font,
        recommender,
        avatar,
    )
    logger.info(f"[musiccard] 卡片已写入：{output_path.name}")
    return {"path": str(output_path), "song": detail}
