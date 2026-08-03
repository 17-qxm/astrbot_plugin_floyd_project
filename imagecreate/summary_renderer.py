"""Pillow 绘制每日/每周打卡总结卡（与歌曲卡片同风格）。

放弃 html_render（Playwright 截图），改用 PIL 直接绘制：
- 纯本地、无外部渲染依赖、文件小（PNG，几十 KB）
- 视觉语言与 card_renderer 一致：深色磨砂、圆角、封面模糊背景

本模块是同步的 CPU/IO(PIL) 工作，由调用方用 ``asyncio.to_thread`` 包裹。

依赖：封面/头像字节由调用方（scheduler，经 netease 异步下载）传入。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .card_renderer import FontLoader, WHITE, _round_corners, _find_font

SCRIPT_DIR = Path(__file__).resolve().parent
FONT_PATH = str(SCRIPT_DIR / "Harmonyossans.ttf") if (SCRIPT_DIR / "Harmonyossans.ttf").is_file() else None

# 调色板（与 card_renderer / HTML 模板一致）
BG = (15, 18, 38)            # #0f1226 整体背景
PANEL = (26, 31, 61)         # #1a1f3d 卡片底
PANEL_BORDER = (42, 49, 88)  # #2a3158
TEXT = (231, 233, 243)       # #e7e9f3
TEXT_DIM = (154, 160, 192)   # #9aa0c0
TEXT_FAINT = (107, 113, 150) # #6b7196
ACCENT = (124, 156, 255)     # #7c9cff
WHITE_DIM = (216, 216, 216)
ACCENT_BAR = (124, 156, 255)


def _blur_cover_bg(cover_bytes: Optional[bytes], size: tuple[int, int]) -> Image.Image:
    """封面放大 + 强模糊 + 暗化遮罩，作为窄条背景。无封面时返回纯色。"""
    w, h = size
    if not cover_bytes:
        return Image.new("RGB", (w, h), PANEL)
    try:
        cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return Image.new("RGB", (w, h), PANEL)
    bg = ImageOps.fit(cover, (w, h), method=Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=22))
    # 暗化遮罩（与 HTML 模板的 0.42 透明度等价）
    over = Image.new("RGBA", (w, h), (15, 18, 38, 120))
    return Image.alpha_composite(bg.convert("RGBA"), over).convert("RGB")


def _circle_avatar(avatar_bytes: Optional[bytes], diameter: int, name: str, font) -> Image.Image:
    """圆形头像；无字节时画首字母占位圆。"""
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = ImageOps.fit(av, (diameter, diameter), method=Image.LANCZOS)
        except Exception:  # noqa: BLE001
            avatar_bytes = None
    if not avatar_bytes:
        av = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
        d = ImageDraw.Draw(av)
        d.ellipse((0, 0, diameter - 1, diameter - 1), fill=(92, 100, 118, 255))
        initial = (name or "?")[0]
        bbox = d.textbbox((0, 0), initial, font=font)
        ix = (diameter - (bbox[2] - bbox[0])) / 2 - bbox[0]
        iy = (diameter - (bbox[3] - bbox[1])) / 2 - bbox[1]
        d.text((ix, iy), initial, font=font, fill=WHITE)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    out = av.copy()
    out.putalpha(mask)
    return out


def _truncate(draw, text, font, max_width):
    """按像素宽度截断文本，超长加省略号。"""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while len(text) > 1 and draw.textlength(text + "\u2026", font=font) > max_width:
        text = text[:-1]
    return text + "\u2026"


def _draw_stat_card(canvas, x, y, w, h, num, label, fonts, S=1):
    """画一张统计小卡片。"""
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x, y, x + w, y + h), radius=16 * S, fill=PANEL, outline=PANEL_BORDER, width=1 * S)
    f_num = fonts.get(40 * S)
    f_lbl = fonts.get(15 * S)
    bbox = d.textbbox((0, 0), str(num), font=f_num)
    d.text((x + 24 * S, y + 18 * S), str(num), font=f_num, fill=ACCENT)
    d.text((x + 24 * S, y + 18 * S + (bbox[3] - bbox[1]) + 12 * S), label, font=f_lbl, fill=TEXT_DIM)


def render_daily(
    checkins: list[dict],
    *,
    date_str: str,
    total_users: int,
    output_path: str,
    assets: Optional[dict] = None,
) -> str:
    """绘制每日总结卡。

    Args:
        checkins: 已按时间排序的列表，每项含 name/song/artist/time/uid。
        assets: {uid: {"avatar": bytes|None}, song_key: {"cover": bytes|None}}。
            封面 key 用 checkin 在列表里的索引 "cover_0"/"cover_1"...。
            为空则不画封面背景/头像图（用占位）。
    Returns:
        output_path。
    """
    assets = assets or {}
    fonts = FontLoader(FONT_PATH)
    S = 2  # 渲染倍率（@2x，提升清晰度）
    W = 760 * S
    PAD = 28 * S
    TRACK_H = 108 * S
    TRACK_GAP = 10 * S
    n = len(checkins)

    # 高度：顶栏 + 副标题 + 统计行 + 间隔 + (n 个曲目条) + 页脚
    top_h = 110 * S          # 标题 + 副标题
    stat_h = 90 * S          # 统计卡
    stat_gap = 22 * S
    section_title_h = 34 * S
    footer_h = 44 * S
    content_h = section_title_h + (n * TRACK_H) + (max(0, n - 1) * TRACK_GAP) if n else 120 * S
    H = PAD * 2 + top_h + stat_h + stat_gap + content_h + footer_h
    H = max(H, 560 * S)      # 最小高度，防扁

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # ---- 标题 ----
    f_title = fonts.get(30 * S)
    f_sub = fonts.get(15 * S)
    d.text((PAD, PAD), "每日打卡总结", font=f_title, fill=TEXT)
    # 标题右对齐日期，用稍小字体
    f_date = fonts.get(20 * S)
    date_w = d.textlength(date_str, font=f_date)
    d.text((W - PAD - date_w, PAD + 6 * S), date_str, font=f_date, fill=TEXT_DIM)
    d.text((PAD, PAD + 44 * S), f"今日歌单 · 共 {n} 首", font=f_sub, fill=TEXT_FAINT)

    # ---- 统计卡 ----
    stat_y = PAD + top_h
    card_w = (W - PAD * 2 - 16 * S) // 2
    _draw_stat_card(canvas, PAD, stat_y, card_w, stat_h, n, "今日打卡", fonts, S)
    _draw_stat_card(canvas, PAD + card_w + 16 * S, stat_y, card_w, stat_h, total_users, "累计参与", fonts, S)

    # ---- 曲目区 ----
    section_y = stat_y + stat_h + stat_gap
    f_sec = fonts.get(18 * S)
    d.text((PAD, section_y), "今日分享（按时间）", font=f_sec, fill=(205, 210, 238))
    y = section_y + section_title_h

    if not n:
        f_empty = fonts.get(16 * S)
        d.text((PAD + 8 * S, y + 30 * S), "今天还没有人打卡", font=f_empty, fill=(139, 145, 181))
        d.text((PAD + 8 * S, y + 58 * S), "快来分享第一首歌吧！", font=f_empty, fill=(139, 145, 181))
    else:
        for i, c in enumerate(checkins):
            cover_bytes = (assets.get(f"cover_{i}") or {}).get("cover")
            avatar_bytes = (assets.get(c.get("uid", "")) or {}).get("avatar")
            _draw_track(canvas, d, PAD, y, W - PAD * 2, TRACK_H, c, cover_bytes, avatar_bytes, fonts, S)
            y += TRACK_H + TRACK_GAP

    # ---- 页脚 ----
    f_foot = fonts.get(13 * S)
    foot = "Floyd · 乐队群每日推歌挑战"
    fw = d.textlength(foot, font=f_foot)
    d.text(((W - fw) / 2, H - PAD - 16 * S), foot, font=f_foot, fill=TEXT_FAINT)

    canvas.save(output_path, "PNG")
    return output_path


def _draw_track(canvas, d, x, y, w, h, checkin, cover_bytes, avatar_bytes, fonts, S=1):
    """画单首歌的窄条：封面模糊背景 + 暗化 + 内容层。"""
    # 圆角背景：先在透明层画矩形 bg，应用圆角 alpha，再贴回 canvas。
    # 注意不能先 paste 矩形 bg 到 canvas——那样圆角外会留下直角填充。
    bg = _blur_cover_bg(cover_bytes, (w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=14 * S, fill=255)
    rounded = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rounded.paste(bg, (0, 0))
    rounded.putalpha(mask)
    canvas.paste(rounded, (x, y), rounded)
    d = ImageDraw.Draw(canvas)

    # 边框
    d.rounded_rectangle((x, y, x + w, y + h), radius=14 * S, outline=PANEL_BORDER, width=1 * S)

    cover_side = h - 28 * S
    cx = x + 14 * S
    cy = y + 14 * S

    # 小封面（圆角）
    if cover_bytes:
        try:
            thumb = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
            thumb = ImageOps.fit(thumb, (cover_side, cover_side), method=Image.LANCZOS)
            thumb = _round_corners(thumb, 10 * S)
            canvas.paste(thumb, (cx, cy), thumb)
        except Exception:  # noqa: BLE001
            d.rounded_rectangle((cx, cy, cx + cover_side, cy + cover_side), radius=10 * S, fill=PANEL)
    else:
        d.rounded_rectangle((cx, cy, cx + cover_side, cy + cover_side), radius=10 * S, fill=PANEL)

    # 文字区
    tx = cx + cover_side + 16 * S
    tw = w - (tx - x) - 200 * S  # 右侧留给推荐人/时间
    f_song = fonts.get(20 * S)
    f_artist = fonts.get(14 * S)
    song = _truncate(d, checkin.get("song", "?"), f_song, tw)
    d.text((tx, cy + 10 * S), song, font=f_song, fill=WHITE)
    artist = _truncate(d, checkin.get("artist", ""), f_artist, tw)
    d.text((tx, cy + 40 * S), artist, font=f_artist, fill=WHITE_DIM)

    # 右侧：时间标签 + 推荐人
    rx = x + w - 14 * S
    f_time = fonts.get(13 * S)
    time_str = checkin.get("time", "")
    tw_w = d.textlength(time_str, font=f_time) + 18 * S
    # 时间毛玻璃块
    d.rounded_rectangle((rx - tw_w, cy + 8 * S, rx, cy + 8 * S + 24 * S), radius=8 * S, fill=(124, 156, 255, 100))
    tb = d.textbbox((0, 0), time_str, font=f_time)
    d.text((rx - tw_w + 9 * S, cy + 8 * S + (24 * S - (tb[3] - tb[1])) / 2 - tb[1]), time_str, font=f_time, fill=WHITE)

    # 推荐人：由 [头像] [名] 推荐，靠右
    f_by = fonts.get(13 * S)
    name = checkin.get("name", "?")
    av_d = 26 * S
    av = _circle_avatar(avatar_bytes, av_d, name, fonts.get(13 * S))
    by_text = f"推荐"
    you_w = d.textlength("由", font=f_by)
    name_w = d.textlength(name, f_by)
    by_w = d.textlength(by_text, font=f_by)
    gap = 6 * S
    total_w = you_w + gap + av_d + gap + name_w + gap + by_w
    sx = rx - total_w
    ay = cy + h - 28 * S - 14 * S
    d.text((sx, ay + (av_d - 16 * S) / 2), "由", font=f_by, fill=TEXT_DIM)
    canvas.paste(av, (int(sx + you_w + gap), int(ay)), av)
    d.text((sx + you_w + gap + av_d + gap, ay + (av_d - 16 * S) / 2), name, font=f_by, fill=WHITE)
    d.text((sx + you_w + gap + av_d + gap + name_w + gap, ay + (av_d - 16 * S) / 2), by_text, font=f_by, fill=TEXT_DIM)


def render_weekly(
    days: list[dict],
    *,
    start: str,
    end: str,
    total_checkins: int,
    participants: int,
    output_path: str,
    assets: Optional[dict] = None,
) -> str:
    """绘制每周总结卡。

    Args:
        days: get_week() 返回的 days 列表，每项 {date, weekday, count, checkins}。
        assets: 同 render_daily，但 key 含天索引 "d{i}_cover_{j}"。
    """
    assets = assets or {}
    fonts = FontLoader(FONT_PATH)
    S = 2  # 渲染倍率（@2x，提升清晰度）
    W = 760 * S
    PAD = 32 * S

    # 统计区高度
    top_h = 70 * S
    stat_h = 90 * S
    stat_gap = 18 * S
    bar_h = 168 * S    # 横向趋势图：标题(24) + 7行×(14+6) + 余量
    bar_gap = 18 * S

    # 每天一组：标题(28) + 间隔(8) + 曲目
    track_h = 56 * S
    track_gap = 8 * S
    day_head_h = 30 * S
    day_gap = 18 * S

    def day_height(day):
        n = len(day.get("checkins", []))
        return day_head_h + (n * track_h + max(0, n - 1) * track_gap if n else 24 * S) + 8 * S

    days_h = sum(day_height(dd) for dd in days) + (len(days) - 1) * day_gap
    footer_h = 40 * S
    H = PAD * 2 + top_h + stat_h + stat_gap + bar_h + bar_gap + days_h + footer_h
    H = max(H, 600 * S)

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # ---- 标题 ----
    f_title = fonts.get(28 * S)
    f_range = fonts.get(16 * S)
    d.text((PAD, PAD), "每周打卡总结", font=f_title, fill=TEXT)
    rng = f"{start} ~ {end}"
    rw = d.textlength(rng, font=f_range)
    d.text((W - PAD - rw, PAD + 8 * S), rng, font=f_range, fill=TEXT_DIM)
    sub = f"本周共分享 {total_checkins} 首 · {participants} 人参与"
    d.text((PAD, PAD + 42 * S), sub, font=fonts.get(14 * S), fill=TEXT_FAINT)

    # ---- 统计卡（3张）----
    sy = PAD + top_h
    card_w = (W - PAD * 2 - 32 * S) // 3
    daily_avg = total_checkins / 7 if total_checkins else 0
    avg_str = f"{daily_avg:.1f}"
    _draw_stat_card(canvas, PAD, sy, card_w, stat_h, total_checkins, "本周打卡", fonts, S)
    _draw_stat_card(canvas, PAD + card_w + 16 * S, sy, card_w, stat_h, participants, "参与人数", fonts, S)
    _draw_stat_card(canvas, PAD + (card_w + 16 * S) * 2, sy, card_w, stat_h, avg_str, "日均(首/天)", fonts, S)

    # ---- 柱状趋势（横向条形图：7 行，每行一个水平条）----
    by = sy + stat_h + stat_gap
    d.text((PAD, by), "7 天趋势", font=fonts.get(16 * S), fill=(205, 210, 238))
    bar_top = by + 24 * S
    row_h = 14 * S
    row_gap = 6 * S
    max_cnt = max([dd.get("count", 0) for dd in days] or [1])
    label_w = 36 * S          # 左侧星期标签宽度
    num_w = 24 * S            # 右侧数值宽度
    bar_x = PAD + label_w
    bar_full_w = W - PAD * 2 - label_w - num_w
    for i, dd in enumerate(days):
        cnt = dd.get("count", 0)
        ry = bar_top + i * (row_h + row_gap)
        # 星期标签
        wd = dd.get("weekday", "")
        f_wd = fonts.get(11 * S)
        ww = d.textlength(wd, font=f_wd)
        d.text((PAD + (label_w - ww) / 2, ry + (row_h - 11 * S) / 2), wd, font=f_wd, fill=TEXT_FAINT)
        # 水平条（底色 + 填充）
        d.rounded_rectangle((bar_x, ry, bar_x + bar_full_w, ry + row_h), radius=4 * S, fill=PANEL)
        if cnt:
            fill_w = int(cnt / max(1, max_cnt) * bar_full_w)
            # 按打卡占比分 4 级配色：少→暗紫，多→亮紫
            ratio = cnt / max(1, max_cnt)
            if ratio <= 0.25:
                bar_color = (91, 76, 145)     # #5b4c91
            elif ratio <= 0.5:
                bar_color = (124, 92, 200)    # #7c5cc8
            elif ratio <= 0.75:
                bar_color = (149, 117, 235)   # #9575eb
            else:
                bar_color = (180, 148, 255)   # #b494ff
            d.rounded_rectangle((bar_x, ry, bar_x + fill_w, ry + row_h), radius=4 * S, fill=bar_color)
        # 数值（右侧）
        f_num = fonts.get(11 * S)
        ns = str(cnt)
        nw = d.textlength(ns, font=f_num)
        d.text((bar_x + bar_full_w + (num_w - nw) / 2, ry + (row_h - 11 * S) / 2), ns, font=f_num, fill=TEXT_DIM)

    # ---- 按天分组 ----
    # 趋势图实际底部 = 第一行 + 7行高度
    trend_bottom = bar_top + 7 * (row_h + row_gap)
    gy = trend_bottom + bar_gap + 26 * S
    f_day = fonts.get(15 * S)
    f_sec2 = fonts.get(16 * S)
    d.text((PAD, gy - 26 * S), "本周歌单", font=f_sec2, fill=(205, 210, 238))

    for di, day in enumerate(days):
        checkins = day.get("checkins", [])
        # 日期标题
        d.text((PAD, gy), f"{day['date']}  {day['weekday']}", font=f_day, fill=ACCENT)
        cnt_str = f"{day['count']} 首"
        cw = d.textlength(cnt_str, font=fonts.get(13 * S))
        d.text((W - PAD - cw, gy + 2 * S), cnt_str, font=fonts.get(13 * S), fill=TEXT_FAINT)
        gy += day_head_h

        if not checkins:
            d.text((PAD + 16 * S, gy), "这天没有人打卡", font=fonts.get(13 * S), fill=TEXT_FAINT)
            gy += 24 * S
        else:
            for ci, c in enumerate(checkins):
                cover_bytes = (assets.get(f"d{di}_cover_{ci}") or {}).get("cover")
                avatar_bytes = (assets.get(c.get("uid", "")) or {}).get("avatar")
                _draw_track_compact(canvas, d, PAD, gy, W - PAD * 2, track_h, c, cover_bytes, avatar_bytes, fonts, S)
                gy += track_h + (track_gap if ci < len(checkins) - 1 else 0)
        gy += day_gap

    # ---- 页脚 ----
    f_foot = fonts.get(13 * S)
    foot = "Floyd · 乐队群每周推歌挑战"
    fw = d.textlength(foot, font=f_foot)
    d.text(((W - fw) / 2, H - PAD - 14 * S), foot, font=f_foot, fill=TEXT_FAINT)

    canvas.save(output_path, "PNG")
    return output_path


def _draw_track_compact(canvas, d, x, y, w, h, checkin, cover_bytes, avatar_bytes, fonts, S=1):
    """周报里的紧凑曲目条（比每日的窄）。"""
    bg = _blur_cover_bg(cover_bytes, (w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=10 * S, fill=255)
    rounded = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rounded.paste(bg, (0, 0))
    rounded.putalpha(mask)
    canvas.paste(rounded, (x, y), rounded)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((x, y, x + w, y + h), radius=10 * S, outline=PANEL_BORDER, width=1 * S)

    cover_side = h - 14 * S
    cx = x + 7 * S
    cy = y + 7 * S
    if cover_bytes:
        try:
            thumb = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
            thumb = ImageOps.fit(thumb, (cover_side, cover_side), method=Image.LANCZOS)
            thumb = _round_corners(thumb, 7 * S)
            canvas.paste(thumb, (cx, cy), thumb)
        except Exception:  # noqa: BLE001
            d.rounded_rectangle((cx, cy, cx + cover_side, cy + cover_side), radius=7 * S, fill=PANEL)
    else:
        d.rounded_rectangle((cx, cy, cx + cover_side, cy + cover_side), radius=7 * S, fill=PANEL)

    tx = cx + cover_side + 12 * S
    tw = w - (tx - x) - 210 * S
    f_song = fonts.get(16 * S)
    f_sub = fonts.get(12 * S)
    song = _truncate(d, checkin.get("song", "?"), f_song, tw)
    d.text((tx, cy + 5 * S), song, font=f_song, fill=WHITE)
    sub = _truncate(d, checkin.get("artist", ""), f_sub, tw)
    d.text((tx, cy + 28 * S), sub, font=f_sub, fill=WHITE_DIM)

    # 右侧：推荐人(小头像+名) + 时间
    rx = x + w - 12 * S
    f_by = fonts.get(12 * S)
    f_time = fonts.get(11 * S)
    name = checkin.get("name", "?")
    av_d = 18 * S
    av = _circle_avatar(avatar_bytes, av_d, name, fonts.get(11 * S))
    name_w = d.textlength(name, font=f_by)
    you_w = d.textlength("由", font=f_by)
    rec_w = d.textlength("推荐", font=f_by)
    gap = 4 * S
    total_w = you_w + gap + av_d + gap + name_w + gap + rec_w
    sx = rx - total_w
    ay = cy + h - 32 * S
    d.text((sx, ay + 1 * S), "由", font=f_by, fill=TEXT_DIM)
    canvas.paste(av, (int(sx + you_w + gap), int(ay - 1 * S)), av)
    d.text((sx + you_w + gap + av_d + gap, ay + 1 * S), name, font=f_by, fill=WHITE)
    d.text((sx + you_w + gap + av_d + gap + name_w + gap, ay + 1 * S), "推荐", font=f_by, fill=TEXT_DIM)

    # 时间（右上角毛玻璃标签，与每日卡片布局一致）
    time_str = checkin.get("time", "")
    tw_w = d.textlength(time_str, font=f_time) + 12 * S
    d.rounded_rectangle((rx - tw_w, cy + 4 * S, rx, cy + 4 * S + 18 * S), radius=5 * S, fill=(124, 156, 255, 90))
    tb = d.textbbox((0, 0), time_str, font=f_time)
    d.text((rx - tw_w + 6 * S, cy + 4 * S + (18 * S - (tb[3] - tb[1])) / 2 - tb[1]), time_str, font=f_time, fill=WHITE)
