"""网易云音乐信息获取（全程异步，基于 aiohttp）。

把原先同步 requests 的逻辑改写为 async，避免阻塞 AstrBot 事件循环。
所有函数：
- ``extract_song_id``：从任意字符串提取歌曲 id（纯 CPU，无需 await）。
- ``fetch_song_detail``：走网易云 web 端接口取歌曲详情。
- ``download_cover`` / ``download_qq_avatar``：下载二进制图片。
"""

from __future__ import annotations

import re
from typing import Optional

import aiohttp

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com",
}

# 由特殊到一般：先匹配完整 music.163.com 链接，再退化到任意 id= 片段。
_ID_PATTERNS = [
    re.compile(r"music\.163\.com[^\s\"'\\<>]*?(?:song|url)[^\s\"'\\<>]*?\?id=(\d+)"),
    re.compile(r"(?:song|url)\?id=(\d+)"),
    re.compile(r"[?&]id=(\d+)"),
]

# QQ 头像服务（q.qlogo.cn）用于卡片底部「推荐人」头像。
_AVATAR_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
}


def extract_song_id(text: Optional[str]) -> Optional[int]:
    """从任意字符串（消息对象 repr / CQ 码 / 纯 URL）中提取网易云歌曲 id。

    返回 int；无法识别时返回 None。
    """
    if not text:
        return None
    for pat in _ID_PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1))
    return None


async def fetch_song_detail(song_id: int, *, timeout: int = 10) -> dict:
    """调用网易云 web 端接口获取歌曲详情。

    Raises:
        ValueError: 接口返回空歌曲列表（下架 / 需登录）。
        aiohttp.ClientError: 网络层错误。
    """
    url = f"https://music.163.com/api/song/detail/?ids=[{song_id}]"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

    songs = data.get("songs") or []
    if not songs:
        raise ValueError(f"未找到歌曲 {song_id}（可能已下架或需要登录）")
    s = songs[0]
    artists = [a.get("name", "") for a in s.get("artists", []) if a.get("name")]
    album = s.get("album") or {}
    cover_url = album.get("picUrl", "") or s.get("picUrl", "") or ""
    return {
        "id": song_id,
        "name": s.get("name", "未知歌曲"),
        "artists": " / ".join(artists) or "未知歌手",
        "album": album.get("name", "") or "未知专辑",
        "cover_url": cover_url,
        "duration": s.get("duration", 0),
    }


async def _get_bytes(session: aiohttp.ClientSession, url: str, *, timeout: int) -> bytes:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        resp.raise_for_status()
        return await resp.read()


async def download_cover(url: str, *, timeout: int = 15) -> bytes:
    """下载封面图，返回原始字节；自动请求 500x500 高清。"""
    if not url:
        raise ValueError("歌曲无封面 URL")
    if "?" not in url:
        url = url + "?param=500x500"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        return await _get_bytes(session, url, timeout=timeout)


async def download_qq_avatar(qq: str, *, timeout: int = 10) -> Optional[bytes]:
    """通过 QQ 号获取高清头像，返回图片字节；失败时返回 None（不抛错）。"""
    if not qq:
        return None
    url = f"https://q.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640&img_type=jpg"
    try:
        async with aiohttp.ClientSession(headers=_AVATAR_HEADERS) as session:
            return await _get_bytes(session, url, timeout=timeout)
    except (aiohttp.ClientError, ValueError):
        return None
