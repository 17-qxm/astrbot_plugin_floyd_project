"""定时调度：每日推歌 & 每日总结，以及群消息发送与 umo 跨平台适配。

umo（unified_msg_origin）的格式随平台不同（如 ``Floyd:GroupMessage:<gid>``）。
本模块从群消息事件里**捕获并缓存**真实 umo 到 KV，定时推送时复用，
避免写死 ``Floyd:GroupMessage:`` 这类前缀。
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain

import ai_generator
import challenge as challenge_mod
import checkin as checkin_mod

PLUGIN_DIR = Path(__file__).resolve().parent
CARD_CACHE_DIR = PLUGIN_DIR / "card_cache"

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
        logger.info(f"[scheduler] 时间格式非法 '{target_hhmm}'，回落到 08:00")
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
        logger.info(f"[scheduler] 未缓存群 {group_id} 的 umo，跳过发送（先在该群发条消息让插件捕获 umo）")
        return False
    try:
        await context.send_message(umo, MessageChain().message(text))
        logger.info(f"[scheduler] 文本已发送到群 {group_id}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.info(f"[scheduler] 发送到群 {group_id} 失败: {e}")
        return False


async def send_image_to_group(plugin: Any, context: Any, group_id: str, image_path: str) -> bool:
    umo = await get_group_umo(plugin, group_id)
    if not umo:
        logger.info(f"[scheduler] 未缓存群 {group_id} 的 umo，跳过发送图片")
        return False
    try:
        await context.send_message(umo, MessageChain().file_image(image_path))
        logger.info(f"[scheduler] 图片已发送到群 {group_id}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.info(f"[scheduler] 发送图片到群 {group_id} 失败: {e}")
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
            secs = seconds_until(cfg["push_time"])
            logger.info(f"[scheduler] 下次推歌将在 {int(secs)} 秒后（{cfg['push_time']}）")
            await asyncio.sleep(secs)
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
                logger.info("[scheduler] 今日无推歌文案，跳过")
            else:
                groups = cfg["target_groups"]
                if groups:
                    sent, failed = await broadcast_text(plugin, context, groups, text)
                    logger.info(f"[scheduler] 今日推歌已发送：成功 {len(sent)} 群，失败 {len(failed)} 群")
                    if failed:
                        logger.info(f"[scheduler] 推歌发送失败的群: {failed}")
            await _mark_done(plugin, "push", today)
            await asyncio.sleep(60)  # 避免循环里再次命中同一时刻
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.info(f"[scheduler] 推歌任务出错: {e}")
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
            secs = seconds_until(cfg["summary_time"])
            logger.info(f"[scheduler] 下次每日总结将在 {int(secs)} 秒后（{cfg['summary_time']}）")
            await asyncio.sleep(secs)
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
                logger.info(f"[scheduler] 每日总结卡片已渲染：{today.isoformat()}，{len(checkins)} 首歌")
                sent, failed = await broadcast_image(plugin, context, groups, image_path)
                logger.info(f"[scheduler] 每日总结已发送：成功 {len(sent)} 群，失败 {len(failed)} 群")
                # 发图失败的群补发文本
                if failed:
                    text = await build_summary_text(store, today=today)
                    await broadcast_text(plugin, context, failed, text)
            else:
                text = await build_summary_text(store, today=today)
                await broadcast_text(plugin, context, groups, text)
                logger.info(f"[scheduler] 每日总结（纯文本）已发送到 {len(groups)} 群")

            await _mark_done(plugin, "summary", today)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.info(f"[scheduler] 总结任务出错: {e}")
            traceback.print_exc()
            await asyncio.sleep(300)


async def _safe_download(coro_func, *args) -> Optional[bytes]:
    """安全执行下载协程，失败返回 None（不影响整体渲染）。"""
    try:
        return await coro_func(*args)
    except Exception as e:  # noqa: BLE001
        logger.info(f"[scheduler] 资源下载失败 ({coro_func.__name__}): {e}")
        return None


async def _download_assets(checkins: list, cover_key_prefix: str = "cover") -> dict:
    """并发下载一批打卡记录的封面 + 头像。

    封面 key: ``{prefix}_{i}``（i 为 checkins 内索引）；
    头像 key: ``uid``（去重）。
    单个失败返回 None，渲染层用占位圆/纯色兜底。
    """
    import netease

    async def _cover(i, url):
        return (f"{cover_key_prefix}_{i}", await _safe_download(netease.download_cover, url))

    async def _avatar(uid):
        return (uid, await _safe_download(netease.download_qq_avatar, uid))

    cover_jobs = [_cover(i, c["cover_url"]) for i, c in enumerate(checkins) if c.get("cover_url")]
    uids = {c.get("uid") for c in checkins if c.get("uid")}
    avatar_jobs = [_avatar(uid) for uid in uids]

    pairs = await asyncio.gather(*cover_jobs, *avatar_jobs, return_exceptions=True)
    assets: dict = {}
    for p in pairs:
        if isinstance(p, Exception):
            continue
        k, b = p
        # 头像结果区分：key 是 uid → avatar；封面 key 含 prefix → cover
        if k.startswith(cover_key_prefix):
            assets[k] = {"cover": b}
        else:
            assets[k] = {"avatar": b}
    return assets


async def _render_summary_card(
    plugin: Any, today: date, checkins: list, stats: dict
) -> Optional[str]:
    """渲染每日总结卡片图（PIL 绘制，与歌曲卡同风格）。

    checkins 已是按打卡时间升序排列的 list（来自 get_today_sorted），
    每项含 name/song/artist/cover_url/time/uid。
    """
    from imagecreate import summary_renderer as sr
    try:
        logger.info(f"[scheduler] 开始渲染每日总结：{len(checkins)} 首歌")
        assets = await _download_assets(checkins)
        logger.info(f"[scheduler] 资源下载完成：{len(assets)} 项")
        out = CARD_CACHE_DIR / f"summary_{today.isoformat()}_{uuid.uuid4().hex[:8]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            sr.render_daily,
            checkins,
            date_str=today.isoformat(),
            total_users=len(stats.get("users", {})),
            output_path=str(out),
            assets=assets,
        )
        logger.info(f"[scheduler] 每日总结卡片已渲染：{out.name}")
        return str(out)
    except Exception as e:  # noqa: BLE001
        logger.info(f"[scheduler] 总结卡片渲染失败: {e}")
        logger.info(traceback.format_exc())
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
    """渲染每周总结卡片图（PIL 绘制，与每日同风格）。失败返回 None。"""
    from imagecreate import summary_renderer as sr
    try:
        week = await plugin.checkin_store.get_week(end)
        days = week["days"]

        # 收集所有 checkins 用于下载封面/头像（按天分组保留位置）。
        # 封面 key: d{di}_cover_{ci}；头像 key: uid（去重，全局复用）。
        all_checkins = [c for day in days for c in day.get("checkins", [])]
        # 用全局 prefix 占位，下载完按 d{di}_cover_{ci} 重建 key
        flat_assets = await _download_assets(all_checkins, cover_key_prefix="flat")

        # 重建带天索引的 assets
        assets: dict = {}
        avatar_map = {k: v for k, v in flat_assets.items() if not k.startswith("flat_")}
        flat_idx = 0
        for di, day in enumerate(days):
            for ci, _c in enumerate(day.get("checkins", [])):
                cover_key = f"flat_{flat_idx}"
                if cover_key in flat_assets:
                    assets[f"d{di}_cover_{ci}"] = flat_assets[cover_key]
                flat_idx += 1
        assets.update(avatar_map)

        out = CARD_CACHE_DIR / f"weekly_{week['end']}_{uuid.uuid4().hex[:8]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            sr.render_weekly,
            days,
            start=week["start"],
            end=week["end"],
            total_checkins=week["total_checkins"],
            participants=week["participants"],
            output_path=str(out),
            assets=assets,
        )
        return str(out)
    except Exception as e:  # noqa: BLE001
        logger.info(f"[scheduler] 周报卡片渲染失败: {e}")
        logger.info(traceback.format_exc())
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
                logger.info(f"[scheduler] 每周总结卡片已渲染（截至 {today.isoformat()}）")
                sent, failed = await broadcast_image(plugin, context, groups, image_path)
                logger.info(f"[scheduler] 每周总结已发送：成功 {len(sent)} 群，失败 {len(failed)} 群")
                if failed:
                    text = await build_weekly_text(plugin.checkin_store, end=today)
                    await broadcast_text(plugin, context, failed, text)
            else:
                text = await build_weekly_text(plugin.checkin_store, end=today)
                await broadcast_text(plugin, context, groups, text)
                logger.info(f"[scheduler] 每周总结（纯文本）已发送到 {len(groups)} 群")

            await plugin.put_kv_data(f"{PUSHED_KEY_PREFIX}{done_key}", "1")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.info(f"[scheduler] 周报任务出错: {e}")
            traceback.print_exc()
            await asyncio.sleep(300)


