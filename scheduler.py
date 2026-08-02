"""定时调度：每日推歌 & 每日总结，以及群消息发送与 umo 跨平台适配。

umo（unified_msg_origin）的格式随平台不同（如 ``Floyd:GroupMessage:<gid>``）。
本模块从群消息事件里**捕获并缓存**真实 umo 到 KV，定时推送时复用，
避免写死 ``Floyd:GroupMessage:`` 这类前缀。
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain

import ai_generator
import challenge as challenge_mod
import checkin as checkin_mod

PLUGIN_DIR = Path(__file__).resolve().parent
SUMMARY_TEMPLATE = PLUGIN_DIR / "templates" / "daily_summary.html"
WEEKLY_TEMPLATE = PLUGIN_DIR / "templates" / "weekly_summary.html"

# html_render 截图参数：JPEG 最高质量 + 设备像素比渲染，避免文字模糊。
# AstrBot 默认是 quality=40 的 JPEG，对文字密集的总结卡片糊到没法看。
# 注：scale 仅支持 "css"/"device"（无数值倍数），device 已是最高清晰度。
RENDER_OPTIONS = {"full_page": True, "type": "jpeg", "quality": 100, "scale": "device"}

UMO_KEY_PREFIX = "umo:"          # group_id -> 缓存的 umo
PUSHED_KEY_PREFIX = "pushed:"    # <date>:<kind> -> "1" 防重复


# ---------- umo 缓存 ----------
async def remember_group_umo(plugin: Any, group_id: str, umo: str) -> None:
    if not group_id or not umo:
        return
    await plugin.put_kv_data(f"{UMO_KEY_PREFIX}{group_id}", umo)


async def get_group_umo(plugin: Any, group_id: str) -> Optional[str]:
    return await plugin.get_kv_data(f"{UMO_KEY_PREFIX}{group_id}", None)


# ---------- 时间计算 ----------
def seconds_until(target_hhmm: str, *, now: Optional[datetime] = None) -> float:
    """计算到下一个 ``HH:MM`` 的秒数（今天已过则顺延到明天）。"""
    now = now or datetime.now()
    try:
        hour, minute = map(int, (target_hhmm or "08:00").split(":"))
    except (ValueError, AttributeError):
        logger.warning(f"[scheduler] 时间格式非法 '{target_hhmm}'，回落到 08:00")
        hour, minute = 8, 0
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


# ---------- 发送助手 ----------
async def send_to_group(plugin: Any, context: Any, group_id: str, text: str) -> bool:
    """向指定群发送一条文本。umo 优先用缓存，缺失则返回 False。"""
    umo = await get_group_umo(plugin, group_id)
    if not umo:
        logger.warning(f"[scheduler] 未缓存群 {group_id} 的 umo，跳过发送（先在该群发条消息让插件捕获 umo）")
        return False
    try:
        await context.send_message(umo, MessageChain().message(text))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"[scheduler] 发送到群 {group_id} 失败: {e}")
        return False


async def send_image_to_group(plugin: Any, context: Any, group_id: str, image_path: str) -> bool:
    umo = await get_group_umo(plugin, group_id)
    if not umo:
        logger.warning(f"[scheduler] 未缓存群 {group_id} 的 umo，跳过发送图片")
        return False
    try:
        await context.send_message(umo, MessageChain().file_image(image_path))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"[scheduler] 发送图片到群 {group_id} 失败: {e}")
        return False


async def broadcast_text(plugin: Any, context: Any, group_ids: list, text: str) -> tuple[list, list]:
    """向多个群发文本，返回 (成功列表, 失败列表)。"""
    sent, failed = [], []
    for g in group_ids:
        if await send_to_group(plugin, context, g, text):
            sent.append(g)
        else:
            failed.append(g)
    return sent, failed


async def broadcast_image(plugin: Any, context: Any, group_ids: list, image_path: str) -> tuple[list, list]:
    """向多个群发图片，返回 (成功列表, 失败列表)。"""
    sent, failed = [], []
    for g in group_ids:
        if await send_image_to_group(plugin, context, g, image_path):
            sent.append(g)
        else:
            failed.append(g)
    return sent, failed


# ---------- 防重复推送 ----------
async def _mark_done(plugin: Any, kind: str, today: Optional[date] = None) -> None:
    today = today or date.today()
    await plugin.put_kv_data(f"{PUSHED_KEY_PREFIX}{today.isoformat()}:{kind}", "1")


async def _is_done(plugin: Any, kind: str, today: Optional[date] = None) -> bool:
    today = today or date.today()
    return (await plugin.get_kv_data(f"{PUSHED_KEY_PREFIX}{today.isoformat()}:{kind}", "")) == "1"


# ---------- 每日推歌 ----------
async def build_push_text(
    manager: challenge_mod.ChallengeManager,
    *,
    start_date: date,
    today: Optional[date] = None,
) -> Optional[str]:
    """构造当日推歌文案（顺序模式）。返回 None 表示无文案或未到起算日。"""
    today = today or date.today()
    item = manager.get_challenge_for_date(today, start_date)
    if not item:
        return None
    return f"🎵 今日推歌挑战 · Day {item['day_number']}\n{item['text']}"


async def run_push_task(plugin: Any, context: Any, cfg: dict, manager: challenge_mod.ChallengeManager) -> None:
    """每日推歌定时循环。"""
    while True:
        try:
            await asyncio.sleep(seconds_until(cfg["push_time"]))
            today = date.today()
            if await _is_done(plugin, "push", today):
                continue

            text: Optional[str]
            if cfg.get("challenge_mode") == "daily_ai":
                day_number = (today - cfg["start_date"]).days + 1 if today >= cfg["start_date"] else 1
                text = await ai_generator.generate_daily(
                    context, manager,
                    day_number=max(day_number, 1),
                    gen_provider=cfg.get("gen_provider", ""),
                    umo_fallback=await get_group_umo(plugin, next(iter(cfg["target_groups"]), "")) or "",
                )
                if text:
                    text = f"🎵 今日推歌挑战 · Day {day_number}\n{text}"
            else:
                text = await build_push_text(manager, start_date=cfg["start_date"], today=today)

            if not text:
                logger.warning("[scheduler] 今日无推歌文案，跳过")
            else:
                groups = cfg["target_groups"]
                if groups:
                    sent, failed = await broadcast_text(plugin, context, groups, text)
                    if failed:
                        logger.warning(f"[scheduler] 推歌发送失败的群: {failed}")
            await _mark_done(plugin, "push", today)
            await asyncio.sleep(60)  # 避免循环里再次命中同一时刻
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"[scheduler] 推歌任务出错: {e}")
            traceback.print_exc()
            await asyncio.sleep(300)


# ---------- 每日总结 ----------
async def build_summary_text(store: checkin_mod.CheckinStore, *, today: Optional[date] = None) -> str:
    """构造当日打卡总结纯文本（按打卡时间排序）。"""
    today = today or date.today()
    today_data = await store.get_today_sorted(today)
    checkins = today_data.get("checkins", [])
    lines = [f"📊 每日打卡总结 · {today.isoformat()}", f"今日打卡：{len(checkins)} 人"]
    if checkins:
        lines.append("")
        for info in checkins:
            song = info.get("song", "?")
            artist = info.get("artist", "")
            name = info.get("name", "?")
            t = info.get("time", "")
            lines.append(f"[{t}] {name} — 《{song}》{(' / ' + artist) if artist else ''}")
    else:
        lines.append("今天还没有人打卡，快来分享第一首歌吧 🎶")
    return "\n".join(lines)


async def run_summary_task(
    plugin: Any, context: Any, cfg: dict, store: checkin_mod.CheckinStore
) -> None:
    """每日总结定时循环。"""
    while True:
        try:
            await asyncio.sleep(seconds_until(cfg["summary_time"]))
            today = date.today()
            if await _is_done(plugin, "summary", today):
                continue

            groups = cfg["target_groups"]
            if not groups:
                continue

            image_path = None
            if cfg.get("auto_summary_image"):
                today_data = await store.get_today_sorted(today)
                checkins = today_data.get("checkins", [])
                stats = await store.get_stats()
                image_path = await _render_summary_card(plugin, today, checkins, stats)

            if image_path:
                sent, failed = await broadcast_image(plugin, context, groups, image_path)
                # 发图失败的群补发文本
                if failed:
                    text = await build_summary_text(store, today=today)
                    await broadcast_text(plugin, context, failed, text)
            else:
                text = await build_summary_text(store, today=today)
                await broadcast_text(plugin, context, groups, text)

            await _mark_done(plugin, "summary", today)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"[scheduler] 总结任务出错: {e}")
            traceback.print_exc()
            await asyncio.sleep(300)


async def _render_summary_card(
    plugin: Any, today: date, checkins: list, stats: dict
) -> Optional[str]:
    """渲染每日总结卡片图（HTML → PNG）。

    checkins 已是按打卡时间升序排列的 list（来自 get_today_sorted），
    每项含 name/song/artist/cover_url/time。
    """
    if not SUMMARY_TEMPLATE.is_file():
        return None
    try:
        tmpl = SUMMARY_TEMPLATE.read_text(encoding="utf-8")
        data = {
            "date": today.isoformat(),
            "count": len(checkins),
            "checkins": checkins,
            "total_users": len(stats.get("users", {})),
        }
        return await plugin.html_render(tmpl, data, return_url=False, options=RENDER_OPTIONS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[scheduler] 总结卡片渲染失败: {e}")
        logger.error(traceback.format_exc())
        return None


# ---------- 每周总结 ----------
async def build_weekly_text(store: checkin_mod.CheckinStore, *, end: Optional[date] = None) -> str:
    """构造本周打卡总结纯文本（按天分组，每天按时间排序）。"""
    week = await store.get_week(end)
    lines = [
        f"📅 每周打卡总结 · {week['start']} ~ {week['end']}",
        f"本周打卡：{week['total_checkins']} 次 · 参与人数：{week['participants']}",
    ]
    for day in week["days"]:
        checkins = day.get("checkins", [])
        lines.append("")
        lines.append(f"— {day['date']} {day['weekday']}（{day['count']} 首）")
        if not checkins:
            lines.append("  （无人打卡）")
        for info in checkins:
            t = info.get("time", "")
            name = info.get("name", "?")
            song = info.get("song", "?")
            artist = info.get("artist", "")
            lines.append(f"  [{t}] {name} — 《{song}》{(' / ' + artist) if artist else ''}")
    return "\n".join(lines)


async def render_weekly_card(plugin: Any, *, end: Optional[date] = None) -> Optional[str]:
    """渲染每周总结卡片图（HTML → PNG）。失败返回 None。"""
    if not WEEKLY_TEMPLATE.is_file():
        return None
    try:
        week = await plugin.checkin_store.get_week(end)
        tmpl = WEEKLY_TEMPLATE.read_text(encoding="utf-8")
        return await plugin.html_render(tmpl, week, return_url=False, options=RENDER_OPTIONS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[scheduler] 周报卡片渲染失败: {e}")
        return None


def seconds_until_weekly(target_hhmm: str, weekday: int, *, now: Optional[datetime] = None) -> float:
    """计算到下一个「指定星期几的 HH:MM」的秒数。

    weekday: 1=周一 ... 7=周日（与 date.isoweekday() 一致）。
    """
    now = now or datetime.now()
    try:
        hour, minute = map(int, (target_hhmm or "22:30").split(":"))
    except ValueError:
        hour, minute = 22, 30
    weekday = max(1, min(7, int(weekday or 7)))

    # 从今天起往后找最近一个满足条件的日子（含今天，若今天时间已过则顺延）。
    for delta in range(8):
        cand = now.date() + timedelta(days=delta)
        if cand.isoweekday() != weekday:
            continue
        cand_dt = datetime.combine(cand, datetime.min.time()).replace(hour=hour, minute=minute)
        if cand_dt > now:
            return (cand_dt - now).total_seconds()
    # 理论上不会走到（8 天内必有目标星期几）
    return 86400.0


async def run_weekly_task(plugin: Any, context: Any, cfg: dict) -> None:
    """每周总结定时循环：在 weekly_day 的 weekly_time 向目标群发本周汇总。"""
    while True:
        try:
            target = seconds_until_weekly(cfg["weekly_time"], cfg["weekly_day"])
            logger.info(f"[scheduler] 下次周报将在 {int(target)} 秒后")
            await asyncio.sleep(target)

            today = date.today()
            # 用「年-周」标记防重复（同年同周只发一次）
            iso_year, iso_week, _ = today.isocalendar()
            done_key = f"weekly:{iso_year}-W{iso_week:02d}"
            if await plugin.get_kv_data(f"{PUSHED_KEY_PREFIX}{done_key}", "") == "1":
                await asyncio.sleep(60)
                continue

            groups = cfg["target_groups"]
            if not groups:
                await asyncio.sleep(60)
                continue

            image_path = None
            if cfg.get("auto_summary_image"):
                image_path = await render_weekly_card(plugin, end=today)

            if image_path:
                sent, failed = await broadcast_image(plugin, context, groups, image_path)
                if failed:
                    text = await build_weekly_text(plugin.checkin_store, end=today)
                    await broadcast_text(plugin, context, failed, text)
            else:
                text = await build_weekly_text(plugin.checkin_store, end=today)
                await broadcast_text(plugin, context, groups, text)

            await plugin.put_kv_data(f"{PUSHED_KEY_PREFIX}{done_key}", "1")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"[scheduler] 周报任务出错: {e}")
            traceback.print_exc()
            await asyncio.sleep(300)


