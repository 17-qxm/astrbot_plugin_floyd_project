"""网易云音乐信息获取（全程异步，基于 aiohttp）。

把原先同步 requests 的逻辑改写为 async，避免阻塞 AstrBot 事件循环。
所有函数：
- ``extract_song_id``：从任意字符串提取歌曲 id（纯 CPU，无需 await）。
- ``fetch_song_detail``：走网易云 web 端接口取歌曲详情。
- ``download_cover``：下载封面二进制。

头像获取已迁至 ``avatar.py``（官方机器人平台按 openid 取头像），
q.qlogo.cn 按 QQ 号取头像的旧链路对 qq_official 无效，已删除。
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


def extract_song_ids(text: Optional[str]) -> list[int]:
    """从任意字符串（消息对象 repr / CQ 码 / 纯 URL）中提取全部网易云歌曲 id。

    按模式优先级去重返回；无匹配返回空列表。
    """
    if not text:
        return []
    ids: list[int] = []
    for pat in _ID_PATTERNS:
        for m in pat.finditer(text):
            v = int(m.group(1))
            if v not in ids:
                ids.append(v)
    return ids


def extract_song_id(text: Optional[str]) -> Optional[int]:
    """从任意字符串（消息对象 repr / CQ 码 / 纯 URL）中提取网易云歌曲 id。

    返回 int；无法识别时返回 None。
    """
    ids = extract_song_ids(text)
    return ids[0] if ids else None


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


# download_qq_avatar 已删除：q.qlogo.cn 只认真实数字 QQ 号，
# qq_official 下 sender_id 是 member_openid。头像获取见 avatar.py。
