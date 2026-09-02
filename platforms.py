"""多平台分享内容解析与信息抓取（全程异步，基于 aiohttp）。

统一对外暴露：
- ``extract_share``：从任意字符串识别平台 + 资源 id（纯 CPU，无需 await）。
- ``fetch_detail``：按平台抓取详情，返回统一 dict 结构。
- ``download_cover``：按平台下载封面（带对应 Referer 防盗链）。

统一详情 dict：
    {
        "platform": "netease" | "bilibili" | "qqmusic" | "kugou",
        "id": 资源 id（int 或 str），
        "name": 标题 / 歌名，
        "artists": 歌手 / UP主，
        "album": 专辑 / 分区 / 来源，
        "cover_url": 封面 URL，
        "duration": 时长（秒，可选），
    }
"""

from __future__ import annotations

import re
from typing import Optional

import aiohttp

import netease

PLATFORM_NETEASE = "netease"
PLATFORM_BILIBILI = "bilibili"
PLATFORM_QQMUSIC = "qqmusic"
PLATFORM_KUGOU = "kugou"
PLATFORM_KUGOU_ALBUM = "kugou_album"

PLATFORM_LABELS = {
    PLATFORM_NETEASE: "网易云音乐",
    PLATFORM_BILIBILI: "哔哩哔哩",
    PLATFORM_QQMUSIC: "QQ音乐",
    PLATFORM_KUGOU: "酷狗音乐",
    PLATFORM_KUGOU_ALBUM: "酷狗专辑",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# 移动端 UA：酷狗分享页（share/album.html）只对移动 UA 在内联 phpParam 里嵌数据。
MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Mobile/15E148"
    ),
}

# B站：完整链接 / b23 短链 / av 号
_BILI_PATTERNS = [
    re.compile(r"bilibili\.com[^\s\"'\\<>]*?/video/(BV[0-9A-Za-z]{10})"),
    re.compile(r"b23\.tv[^\s\"'\\<>]*?/(BV[0-9A-Za-z]{10})"),
    re.compile(r"b23\.tv[^\s\"'\\<>]*?(?:/|\?)(av\d+)"),
    re.compile(r"(?:/video/|^|\s)(BV[0-9A-Za-z]{10})"),
    re.compile(r"(?<![\w])(av\d+)(?![\w])"),
]

# QQ音乐：仅从明确 URL / 参数上下文提取 songmid（避免误伤其它平台消息中的同形字符串）
_QQMUSIC_PATTERNS = [
    re.compile(r"songDetail/([0-9A-Za-z]{10,})"),
    re.compile(r"songmid=([0-9A-Za-z]{10,})"),
    # 捕获须数字开头：songmid 实测均以数字开头，排除 URL 路径词（songDetail）和 JSON 字段串（DownloadVIPGift）
    re.compile(r"y\.qq\.com[^\s\"'\\<>]*?([0-9][0-9A-Za-z]{9,})"),
]

# 酷狗：/song/#hash= / share/info/{hash} / hash= 片段
_KUGOU_PATTERNS = [
    re.compile(r"kugou\.com[^\s\"'\\<>]*?hash=([0-9A-Za-z]{16,})"),
    re.compile(r"kugou\.com/share/info/([0-9A-Za-z]{16,})"),
]

# 酷狗专辑真实分享：t1 短链 / share/album.html 跳转页（id 是编码串，需抓取页面解出数字 albumid）
_KUGOU_ALBUM_SHORT_PATTERNS = [
    re.compile(r"t1\.kugou\.com/album\.html\?id=([0-9A-Za-z]+)"),
    re.compile(r"kugou\.com/share/album\.html[^\s\"'\\<>]*?[?&]id=([0-9A-Za-z]+)"),
]

# 酷狗专辑泛链接：album_id= 参数 / /album/{id} 页面。
# 仅作兜底——单曲分享的 JSON 里常内嵌这类所属专辑链接，和单曲 hash 同时命中会出一张多余的专辑卡。
_KUGOU_ALBUM_GENERIC_PATTERNS = [
    re.compile(r"kugou\.com[^\s\"'\\<>]*?album_id=(\d+)"),
    re.compile(r"kugou\.com[^\s\"'\\<>]*?/album/(\d+)"),
]


def extract_shares(text: Optional[str], limit: int = 5) -> list[tuple[str, str]]:
    """从任意字符串提取全部分享，返回 ``[(platform, resource_id), ...]``。

    收集顺序即平台优先级：B站 > QQ音乐 > 酷狗专辑 > 酷狗单曲 > 网易云
    （网易云 id 是纯数字，regex 最宽松，放最后兜底）。
    按 (platform, id) 去重；limit 封顶，防一条消息链接过多时刷屏。
    """
    shares: list[tuple[str, str]] = []

    def add(platform: str, rid: str) -> None:
        if len(shares) < limit and (platform, rid) not in shares:
            shares.append((platform, rid))

    if not text:
        return shares

    for pats, platform in [
        (_BILI_PATTERNS, PLATFORM_BILIBILI),
        (_QQMUSIC_PATTERNS, PLATFORM_QQMUSIC),
        (_KUGOU_ALBUM_SHORT_PATTERNS, PLATFORM_KUGOU_ALBUM),
        (_KUGOU_PATTERNS, PLATFORM_KUGOU),
    ]:
        for pat in pats:
            for m in pat.finditer(text):
                add(platform, m.group(1))

    # 泛专辑链接仅兜底：命中单曲 hash 或真实专辑短链时放弃泛链接，
    # 避免单曲分享 JSON 内嵌的所属专辑链接多出一张专辑卡。
    has_song = any(p == PLATFORM_KUGOU for p, _ in shares)
    has_short_album = any(p == PLATFORM_KUGOU_ALBUM for p, _ in shares)
    if not has_song and not has_short_album:
        for pat in _KUGOU_ALBUM_GENERIC_PATTERNS:
            for m in pat.finditer(text):
                add(PLATFORM_KUGOU_ALBUM, m.group(1))

    for sid in netease.extract_song_ids(text):
        add(PLATFORM_NETEASE, str(sid))

    return shares


def extract_share(text: Optional[str]) -> Optional[tuple[str, str]]:
    """从任意字符串识别第一个分享来源，返回 ``(platform, resource_id)``；无法识别返回 None。

    优先级同 :func:`extract_shares`。
    """
    shares = extract_shares(text, limit=1)
    return shares[0] if shares else None


async def _get_json(session: aiohttp.ClientSession, url: str, *, referer: str, timeout: int) -> dict:
    headers = dict(HEADERS)
    headers["Referer"] = referer
    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        resp.raise_for_status()
        if "json" in (resp.headers.get("content-type") or ""):
            return await resp.json(content_type=None)
        return await resp.json(content_type=None)


async def _fetch_bilibili(bvid: str, *, timeout: int) -> dict:
    """B站视频：x/web-interface/view（无需登录，返回标题/UP主/封面/播放/时长）。"""
    param = f"bvid={bvid}" if bvid.startswith("BV") else f"aid={bvid[2:]}"
    url = f"https://api.bilibili.com/x/web-interface/view?{param}"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        data = await _get_json(session, url, referer="https://www.bilibili.com/", timeout=timeout)
    if data.get("code") != 0:
        raise ValueError(f"B站视频信息获取失败: {data.get('message', '未知错误')}")
    d = data["data"]
    owner = d.get("owner") or {}
    stat = d.get("stat") or {}
    return {
        "platform": PLATFORM_BILIBILI,
        "id": bvid,
        "name": d.get("title", "未知视频"),
        "artists": owner.get("name", "未知UP主"),
        "album": d.get("tname", "") or "B站视频",
        "cover_url": d.get("pic", ""),
        "duration": d.get("duration", 0),
        "view": stat.get("view", 0),
    }


async def _fetch_qqmusic(songmid: str, *, timeout: int) -> dict:
    """QQ音乐：y.qq.com 单曲接口（songmid 查询）。"""
    url = (
        "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg"
        f"?songmid={songmid}&format=json&platform=yqq.json&needNewCode=0"
    )
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        data = await _get_json(session, url, referer="https://y.qq.com/", timeout=timeout)
    songs = data.get("data") or []
    if not songs:
        raise ValueError(f"QQ音乐歌曲信息获取失败（可能已下架）: {songmid}")
    s = songs[0]
    singers = [a.get("name", "") or a.get("title", "") for a in (s.get("singer") or []) if a.get("name") or a.get("title")]
    album = s.get("album") or {}
    albummid = album.get("mid", "")
    return {
        "platform": PLATFORM_QQMUSIC,
        "id": songmid,
        "name": s.get("name") or s.get("title") or "未知歌曲",
        "artists": " / ".join(singers) or "未知歌手",
        "album": album.get("name") or album.get("title") or "未知专辑",
        "cover_url": f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{albummid}.jpg" if albummid else "",
        "duration": s.get("interval", 0) * 1000,
    }


async def _fetch_kugou(hash_id: str, *, timeout: int) -> dict:
    """酷狗音乐：m.kugou.com getSongInfo（hash 查询）。"""
    url = f"https://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={hash_id}"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        data = await _get_json(session, url, referer="https://www.kugou.com/", timeout=timeout)
    if data.get("errcode") != 0 or not data.get("songName"):
        raise ValueError(f"酷狗歌曲信息获取失败: {data.get('error', '未知错误')} (hash={hash_id})")
    img_url = data.get("imgUrl") or data.get("album_img") or ""
    img_url = img_url.replace("{size}", "400").replace("http://", "https://")
    return {
        "platform": PLATFORM_KUGOU,
        "id": hash_id,
        "name": data.get("songName", "未知歌曲"),
        "artists": data.get("singerName", "未知歌手"),
        "album": data.get("albumName") or "未知专辑",
        "cover_url": img_url,
        "duration": int(data.get("timeLength", "0") or 0),
    }


async def _resolve_kugou_album_code(session: aiohttp.ClientSession, code: str, timeout: int) -> str:
    """专辑短链编码 id → 数字 albumid：跟随 t1 重定向到 share 页，从内联 phpParam 提取。"""
    url = f"https://t1.kugou.com/album.html?id={code}"
    async with session.get(url, headers=MOBILE_HEADERS, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
        html = await resp.text()
    m = re.search(r'"albumid"\s*:\s*(\d+)', html)
    if not m:
        raise ValueError(f"酷狗专辑短链解析失败（页面未含数字 albumid）: {code}")
    return m.group(1)


async def _fetch_kugou_album(album_id: str, *, timeout: int) -> dict:
    """酷狗专辑：mobilecdn v3 album/info（专辑信息）+ album/song（曲目列表）。

    album_id 可能是数字（泛链接）或编码串（真实分享的 t1 短链），后者先解出数字 id。
    """
    # 注意：mobilecdn.kugou.com 的 HTTPS 证书域名不匹配，只能走 HTTP（实测 curl 同样）。
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        if not album_id.isdigit():
            album_id = await _resolve_kugou_album_code(session, album_id, timeout)
        async with session.get(
            f"http://mobilecdn.kugou.com/api/v3/album/info?albumid={album_id}",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            info_data = await resp.json(content_type=None)
        async with session.get(
            f"http://mobilecdn.kugou.com/api/v3/album/song?albumid={album_id}&page=1&pagesize=30",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            songs_data = await resp.json(content_type=None)
    info = info_data.get("data") or {}
    if info_data.get("errcode") != 0 or not info.get("albumname"):
        raise ValueError(f"酷狗专辑信息获取失败: {info_data.get('error', '未知错误')} (album_id={album_id})")
    tracks = []
    for s in (songs_data.get("data") or {}).get("info") or []:
        filename = s.get("filename") or ""
        artist, _, title = filename.partition(" - ")
        tracks.append({
            "name": title or filename or "未知曲目",
            "artists": artist or info.get("singername", "") or "未知歌手",
        })
    img_url = (info.get("imgurl") or "").replace("{size}", "400").replace("http://", "https://")
    return {
        "platform": PLATFORM_KUGOU_ALBUM,
        "id": album_id,
        "name": info.get("albumname", "未知专辑"),
        "artists": info.get("singername", "未知歌手"),
        "album": info.get("albumname", "未知专辑"),
        "cover_url": img_url,
        "tracks": tracks,
        "track_count": int((songs_data.get("data") or {}).get("total") or len(tracks)),
    }


FETCHERS = {
    PLATFORM_NETEASE: lambda rid, *, timeout: netease.fetch_song_detail(int(rid), timeout=timeout),
    PLATFORM_BILIBILI: _fetch_bilibili,
    PLATFORM_QQMUSIC: _fetch_qqmusic,
    PLATFORM_KUGOU: _fetch_kugou,
    PLATFORM_KUGOU_ALBUM: _fetch_kugou_album,
}


async def fetch_detail(platform: str, resource_id: str, *, timeout: int = 15) -> dict:
    """按平台抓取分享内容详情，返回统一 dict；失败抛异常（网络/下架等）。"""
    fetcher = FETCHERS.get(platform)
    if not fetcher:
        raise ValueError(f"未知平台: {platform}")
    detail = await fetcher(resource_id, timeout=timeout)
    detail["platform"] = platform
    detail["platform_label"] = PLATFORM_LABELS.get(platform, platform)
    return detail


_COVER_REFERERS = {
    PLATFORM_NETEASE: "https://music.163.com",
    PLATFORM_BILIBILI: "https://www.bilibili.com/",
    PLATFORM_QQMUSIC: "https://y.qq.com/",
    PLATFORM_KUGOU: "https://www.kugou.com/",
    PLATFORM_KUGOU_ALBUM: "https://www.kugou.com/",
}


async def download_cover(platform: str, url: str, *, timeout: int = 15) -> bytes:
    """下载封面图，返回原始字节。平台决定 Referer 防盗链。"""
    if not url:
        raise ValueError("分享内容无封面 URL")
    referer = _COVER_REFERERS.get(platform, HEADERS["User-Agent"])
    headers = dict(HEADERS)
    headers["Referer"] = referer
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.read()


async def download_qq_avatar(qq: str, *, timeout: int = 10) -> Optional[bytes]:
    """通过 QQ 号获取高清头像（转发 netease 的实现）。"""
    return await netease.download_qq_avatar(qq, timeout=timeout)