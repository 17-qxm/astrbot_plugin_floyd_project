"""Pillow 卡片渲染器（深色磨砂风格歌曲卡片）。

迁移自 musiccard/card_renderer.py，仅做最小清理：
- ``os.path``/``glob`` → ``pathlib``；
- 字体探测支持传入插件根目录。

本模块是同步的 CPU/IO(PIL) 工作，由调用方用 ``asyncio.to_thread`` 包裹，
避免阻塞 AstrBot 事件循环。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent

WHITE = (255, 255, 255)

# 系统 / 常见 CJK 字体兜底路径，用于 WebUI 服务器无自带字体时的回退。
_FONT_FALLBACKS = [
    "C:/Windows/Fonts/HarmonyOS_Sans_SC.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _find_font(font_path: Optional[str] = None) -> Optional[str]:
    """按优先级寻找可用字体路径：显式参数 > 插件目录内置 > 系统兜底。"""
    if font_path and Path(font_path).is_file():
        return font_path
    local = sorted(
        [str(p) for p in SCRIPT_DIR.glob("*.ttf")]
        + [str(p) for p in SCRIPT_DIR.glob("*.otf")]
        + [str(p) for p in SCRIPT_DIR.glob("*.ttc")]
    )
    if local:
        return local[0]
    for candidate in _FONT_FALLBACKS:
        if Path(candidate).is_file():
            return candidate
    return None


class FontLoader:
    """按字号缓存字体对象，避免重复 truetype 解析。"""

    def __init__(self, font_path: Optional[str] = None):
        self.path = _find_font(font_path)
        self._cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def get(self, size: int):
        if size not in self._cache:
            if self.path:
                self._cache[size] = ImageFont.truetype(self.path, size)
            else:
                self._cache[size] = ImageFont.load_default()
        return self._cache[size]


def _round_corners(im: Image.Image, radius: int) -> Image.Image:
    """给图片加圆角透明遮罩。"""
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, im.size[0] - 1, im.size[1] - 1), radius=radius, fill=255
    )
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    """按像素宽度把标题拆成至多 max_lines 行，溢出行用「…」截断。"""
    lines: list[str] = []
    cur = ""
    overflow = False
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) == max_lines:
                overflow = True
                break
    if not overflow and cur:
        lines.append(cur)
    if overflow and lines:
        last = lines[-1]
        while len(last) > 1 and draw.textlength(last + "\u2026", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + "\u2026"
    return lines or [text]


def _make_avatar(
    avatar_bytes: Optional[bytes],
    diameter: int,
    font: ImageFont.FreeTypeFont,
    initial: str,
) -> Image.Image:
    """生成圆形头像；无头像字节时画一个带首字母的占位圆。"""
    size = diameter
    if avatar_bytes:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        av = ImageOps.fit(av, (size, size), method=Image.LANCZOS)
    else:
        av = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(av)
        d.ellipse((0, 0, size - 1, size - 1), fill=(92, 100, 118, 255))
        bbox = d.textbbox((0, 0), initial, font=font)
        ix = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
        iy = (size - (bbox[3] - bbox[1])) / 2 - bbox[1]
        d.text((ix, iy), initial, font=font, fill=WHITE)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    final = av.copy()
    final.putalpha(mask)
    return final


def _draw_platform_badge(
    bg: Image.Image,
    draw: ImageDraw.ImageDraw,
    fonts: "FontLoader",
    platform_label: str,
) -> None:
    """左上角平台徽标：圆角半透明小标签。"""
    f_plat = fonts.get(24)
    plat_bbox = draw.textbbox((0, 0), platform_label, font=f_plat)
    plat_w = plat_bbox[2] - plat_bbox[0] + 24
    plat_h = plat_bbox[3] - plat_bbox[1] + 14
    plat_bg = Image.new("RGBA", (plat_w, plat_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plat_bg)
    pd.rounded_rectangle((0, 0, plat_w - 1, plat_h - 1), radius=plat_h // 2, fill=(0, 0, 0, 110))
    pd.text((12, plat_h // 2 - (plat_bbox[3] - plat_bbox[1]) // 2 - plat_bbox[1]),
            platform_label, font=f_plat, fill=WHITE)
    bg.alpha_composite(plat_bg, (20, 20))


def _draw_recommender_bar(
    bg: Image.Image,
    draw: ImageDraw.ImageDraw,
    fonts: "FontLoader",
    top_h: int,
    card_w: int,
    recommender: Optional[str],
    avatar_bytes: Optional[bytes],
) -> None:
    """底部推荐人条：渐变加深 + 圆形头像 + 文字。"""
    bar_h = 66
    grad = Image.new("RGBA", (card_w, bar_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(bar_h):
        a = int(34 + 70 * (y / max(1, bar_h - 1)))
        gd.line((0, y, card_w, y), fill=(0, 0, 0, a))
    bg.alpha_composite(grad, (0, top_h))

    name = recommender or "未知"
    f_bar = fonts.get(26)
    avatar_d = bar_h - 16
    avatar = _make_avatar(avatar_bytes, avatar_d, f_bar, name[0])
    ax = 44
    ay = top_h + (bar_h - avatar_d) // 2
    bg.alpha_composite(avatar, (ax, ay))

    bar_text = "推荐人：" + name
    bbox = draw.textbbox((0, 0), bar_text, font=f_bar)
    by = top_h + (bar_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((ax + avatar_d + 14, by), bar_text, font=f_bar, fill=(214, 214, 214))


def render_card(
    song: dict,
    cover_bytes: bytes,
    output_path: str,
    font_path: Optional[str] = None,
    recommender: Optional[str] = None,
    avatar_bytes: Optional[bytes] = None,
) -> str:
    """根据歌曲信息与封面字节生成深色磨砂卡片 PNG（圆角窄条 + 底部推荐人头像条）。

    支持多平台：左上角绘制平台徽标；B站视频额外显示 UP主 / 播放 / 时长。

    返回保存后的 output_path。调用方负责把网络下载放到异步层。
    """
    CARD_W, CARD_H = 880, 380
    CARD_RADIUS = 24
    BAR_H = 66
    TOP_H = CARD_H - BAR_H
    PAD = 44
    EDGE = 4
    COVER_SIDE = TOP_H - EDGE * 2

    cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")

    # 背景：封面放大 + 强模糊 + 暗化遮罩。
    bg = ImageOps.fit(cover, (CARD_W, CARD_H), method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=42))
    bg = bg.convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 158)))

    draw = ImageDraw.Draw(bg)
    fonts = FontLoader(font_path)

    cover_x = EDGE
    cover_y = EDGE

    # 封面阴影。
    shadow = Image.new("RGBA", (COVER_SIDE + 60, COVER_SIDE + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (30, 30, COVER_SIDE + 30, COVER_SIDE + 30), radius=22, fill=(0, 0, 0, 120)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    bg.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

    thumb = ImageOps.fit(cover, (COVER_SIDE, COVER_SIDE), method=Image.LANCZOS)
    thumb = _round_corners(thumb, 20)
    bg.paste(thumb, (cover_x, cover_y), thumb)

    # 右侧文字区：标题(两行省略) / 歌手(或UP主) / 专辑。
    tx = cover_x + COVER_SIDE + 44
    tw = CARD_W - tx - PAD
    f_title = fonts.get(56)
    f_artist = fonts.get(36)
    f_album = fonts.get(28)

    # 平台徽标文字。视频/歌曲显示不同副行：视频→分区+时长+播放；音乐→平台+专辑。
    platform = song.get("platform", "")
    platform_label = song.get("platform_label", "") or platform
    is_video = platform == "bilibili"
    if is_video:
        duration_s = int(song.get("duration", 0) or 0)
        m, s = divmod(duration_s, 60)
        h, m = divmod(m, 60)
        dur = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        view = int(song.get("view", 0) or 0)
        view_str = f"{view/10000:.1f}万" if view >= 10000 else str(view)
        meta_line = f"{platform_label} · {song.get('album', '')} · {dur} · 播放 {view_str}"
    else:
        meta_line = f"{platform_label} · {song.get('album', '')}"

    title_lines = _wrap_text(draw, song["name"], f_title, tw, max_lines=2)
    title_line_h = 66
    title_h = len(title_lines) * title_line_h
    artist_h = 48
    album_h = 38
    block_h = title_h + 18 + artist_h + 12 + album_h
    ty = (TOP_H - block_h) // 2

    # 平台徽标：左上角圆角小标签。
    _draw_platform_badge(bg, draw, fonts, platform_label)

    for i, ln in enumerate(title_lines):
        draw.text((tx, ty + i * title_line_h), ln, font=f_title, fill=WHITE)
    ty += title_h + 18
    artist_line = _wrap_text(draw, song["artists"], f_artist, tw, max_lines=1)[0]
    draw.text((tx, ty), artist_line, font=f_artist, fill=(216, 216, 216))
    ty += artist_h + 12
    meta_line = _wrap_text(draw, meta_line, f_album, tw, max_lines=1)[0]
    draw.text((tx, ty), meta_line, font=f_album, fill=(172, 172, 172))

    # 底部推荐人条：渐变加深 + 圆形头像 + 文字。
    grad = Image.new("RGBA", (CARD_W, BAR_H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(BAR_H):
        a = int(34 + 70 * (y / max(1, BAR_H - 1)))
        gd.line((0, y, CARD_W, y), fill=(0, 0, 0, a))
    bg.alpha_composite(grad, (0, TOP_H))

    _draw_recommender_bar(bg, draw, fonts, TOP_H, CARD_W, recommender, avatar_bytes)

    # 整卡圆角。
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=CARD_RADIUS, fill=255)
    bg.putalpha(mask)

    bg.save(output_path, "PNG")
    return output_path


def render_album_card(
    song: dict,
    cover_bytes: bytes,
    output_path: str,
    font_path: Optional[str] = None,
    recommender: Optional[str] = None,
    avatar_bytes: Optional[bytes] = None,
) -> str:
    """专辑卡片（同款深色磨砂风格）：头部专辑封面+名称/歌手，中部曲目列表，底部推荐人条。

    曲目列表至多展示 6 首，超出追加一行「……共 N 首」。

    返回保存后的 output_path。调用方负责把网络下载放到异步层。
    """
    CARD_W, CARD_RADIUS = 880, 24
    BAR_H = 66
    PAD = 44
    COVER_SIDE = 220
    HEADER_PAD = 24
    HEADER_H = HEADER_PAD * 2 + COVER_SIDE
    ROW_H = 52
    LIST_PAD = 18

    tracks = song.get("tracks") or []
    total = int(song.get("track_count") or len(tracks)) or len(tracks)
    shown = tracks[:6]
    extra = total - len(shown)
    row_count = len(shown) + (1 if extra > 0 else 0)
    list_h = row_count * ROW_H + LIST_PAD * 2
    LIST_GAP = 12 if row_count else 0
    CARD_H = HEADER_H + LIST_GAP + list_h + BAR_H
    TOP_H = CARD_H - BAR_H

    cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")

    # 背景：封面放大 + 强模糊 + 暗化遮罩。
    bg = ImageOps.fit(cover, (CARD_W, CARD_H), method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=42))
    bg = bg.convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 158)))

    draw = ImageDraw.Draw(bg)
    fonts = FontLoader(font_path)

    # 头部：左专辑封面，右专辑名(两行省略) / 歌手 / 曲目数。
    thumb = _round_corners(
        ImageOps.fit(cover, (COVER_SIDE, COVER_SIDE), method=Image.LANCZOS), 20
    )
    bg.paste(thumb, (HEADER_PAD, HEADER_PAD), thumb)
    platform_label = song.get("platform_label", "") or song.get("platform", "")
    _draw_platform_badge(bg, draw, fonts, platform_label)

    tx = HEADER_PAD + COVER_SIDE + 36
    tw = CARD_W - tx - PAD
    f_title = fonts.get(48)
    f_artist = fonts.get(32)
    f_meta = fonts.get(26)
    title_lines = _wrap_text(draw, song["name"], f_title, tw, max_lines=2)
    title_line_h = 58
    title_h = len(title_lines) * title_line_h
    artist_h = 44
    meta_h = 34
    block_h = title_h + 14 + artist_h + 10 + meta_h
    ty = HEADER_PAD + (COVER_SIDE - block_h) // 2

    for i, ln in enumerate(title_lines):
        draw.text((tx, ty + i * title_line_h), ln, font=f_title, fill=WHITE)
    ty += title_h + 14
    artist_line = _wrap_text(draw, song["artists"], f_artist, tw, max_lines=1)[0]
    draw.text((tx, ty), artist_line, font=f_artist, fill=(216, 216, 216))
    ty += artist_h + 10
    meta_line = _wrap_text(draw, f"{platform_label} · 专辑 · 共 {total} 首", f_meta, tw, max_lines=1)[0]
    draw.text((tx, ty), meta_line, font=f_meta, fill=(172, 172, 172))

    # 曲目列表：半透明圆角面板 + 序号/曲目/歌手；超出展示数时省略行。
    if row_count:
        ly = HEADER_H + LIST_GAP
        panel_w = CARD_W - HEADER_PAD * 2
        panel = Image.new("RGBA", (panel_w, list_h), (0, 0, 0, 0))
        ImageDraw.Draw(panel).rounded_rectangle(
            (0, 0, panel_w - 1, list_h - 1), radius=16, fill=(0, 0, 0, 96)
        )
        bg.alpha_composite(panel, (HEADER_PAD, ly))

        f_row = fonts.get(28)
        f_more = fonts.get(26)
        row_w = panel_w - 56
        ry = ly + LIST_PAD
        for i, t in enumerate(shown):
            line = f"{i + 1:02d}  {t.get('name', '')}"
            if t.get("artists"):
                line += f" · {t['artists']}"
            line = _wrap_text(draw, line, f_row, row_w, max_lines=1)[0]
            draw.text((HEADER_PAD + 28, ry + (ROW_H - 34) // 2), line, font=f_row, fill=(224, 224, 224))
            ry += ROW_H
        if extra > 0:
            draw.text(
                (HEADER_PAD + 28, ry + (ROW_H - 32) // 2),
                f"……共 {total} 首",
                font=f_more,
                fill=(172, 172, 172),
            )

    # 底部推荐人条 + 整卡圆角。
    _draw_recommender_bar(bg, draw, fonts, TOP_H, CARD_W, recommender, avatar_bytes)

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1), radius=CARD_RADIUS, fill=255)
    bg.putalpha(mask)

    bg.save(output_path, "PNG")
    return output_path
