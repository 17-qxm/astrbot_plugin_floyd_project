"""Floyd 乐队群插件入口。

三大功能：
1. 网易云分享卡片 — 群里发网易云分享，自动生成深色磨砂卡片并回复。
2. 每日推歌挑战 — 定时推送当日主题（顺序轮播 / AI 每日现生成）。
3. 打卡统计 + 每日总结 — 分享即打卡，固定时间发当日汇总。

附带 WebUI 管理面板（pages/admin）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

# 确保子模块可被同目录导入（AstrBot 加载插件时 __file__ 在此目录）。
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

import ai_generator
import card_service
import challenge as challenge_mod
import checkin as checkin_mod
import scheduler as scheduler_mod
from webui import web_api
from netease import extract_song_id

PLUGIN_NAME = "astrbot_plugin_floyd_project"
CARD_OUTPUT_DIR = _CURRENT_DIR / "card_cache"

class FloydPlugin(Star):
    """主插件类。"""

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # 文案管理：存到 plugin_data 下，便于 WebUI 上传/导出。
        data_dir = self._resolve_data_dir()
        self._data_dir = data_dir
        CARD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.challenge_mgr = challenge_mod.ChallengeManager(data_dir / "challenges.json")
        self.checkin_store = checkin_mod.CheckinStore(self)

        # 目标群集合（去重）；既是打卡群也是推送目标。
        raw_groups = config.get("target_groups", []) or []
        if isinstance(raw_groups, str):
            raw_groups = [g.strip() for g in raw_groups.split(",") if g.strip()]
        self.target_groups = [str(g).strip() for g in raw_groups if str(g).strip()]

        # WebAPI（在 initialize 注册，确保 context 就绪；这里先持有实例）。
        self._web_api = web_api.WebAPI(self)

        # 定时任务在 initialize 里创建（async 上下文，事件循环确定运行）。
        self._tasks: list[asyncio.Task] = []

    def _resolve_data_dir(self) -> Path:
        """优先用 AstrBot 的插件数据目录；取不到则回落到插件目录下的 data/。"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            base = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        except Exception:  # noqa: BLE001
            base = _CURRENT_DIR / "data"
        base.mkdir(parents=True, exist_ok=True)
        return base

    async def get_first_known_umo(self) -> str:
        """供 AI 生成回落用：返回任一已缓存的群 umo。"""
        for gid in self.target_groups:
            if gid:
                umo = await scheduler_mod.get_group_umo(self, gid)
                if umo:
                    return umo
        return ""

    # ---------- 生命周期 ----------
    async def initialize(self):
        """首次启动时把随插件附带的 song_push.txt 导入默认文案。"""
        n = challenge_mod.bootstrap_from_default_txt(self.challenge_mgr)
        if n:
            logger.info(f"[floyd] 首次启动，已从 song_push.txt 导入 {n} 条默认文案")

        # 注册 WebUI 后端路由 + DELETE 单独路由。
        try:
            self._web_api.register_all()
            web_api.register_delete_route(self)
            logger.info("[floyd] WebUI 路由已注册")
        except Exception as e:  # noqa: BLE001 — register_web_api 在低版本可能不存在
            logger.info(f"[floyd] WebUI 路由注册失败（可能 AstrBot 版本不支持）: {e}")

        # 启动定时任务（在 initialize 的 async 上下文里创建，事件循环确定运行）。
        cfg = self._scheduler_cfg()
        for name, coro in [
            ("推歌", scheduler_mod.run_push_task(self, self.context, cfg, self.challenge_mgr)),
            ("每日总结", scheduler_mod.run_summary_task(self, self.context, cfg, self.checkin_store)),
            ("每周总结", scheduler_mod.run_weekly_task(self, self.context, cfg)),
        ]:
            t = asyncio.create_task(coro, name=name)

            def _on_done(task, _name=name):
                if task.cancelled():
                    logger.info(f"[floyd] 定时任务「{_name}」已取消")
                elif task.exception():
                    logger.info(f"[floyd] 定时任务「{_name}」异常退出: {task.exception()}")
                else:
                    logger.info(f"[floyd] 定时任务「{_name}」正常结束")
            t.add_done_callback(_on_done)
            self._tasks.append(t)
        logger.info(f"[floyd] 定时任务已启动（推歌 / 每日总结 / 每周总结）")

    def _scheduler_cfg(self) -> dict:
        start_date = challenge_mod.parse_start_date(self.config.get("challenge_start_date", ""))
        return {
            "target_groups": self.target_groups,
            "push_time": self.config.get("push_time", "08:00"),
            "summary_time": self.config.get("summary_time", "22:00"),
            "weekly_time": self.config.get("weekly_time", "22:30"),
            "weekly_day": int(self.config.get("weekly_day", 7) or 7),
            "challenge_mode": self.config.get("challenge_mode", "sequential"),
            "start_date": start_date,
            "gen_provider": self.config.get("gen_provider", ""),
            "auto_summary_image": bool(self.config.get("auto_summary_image", True)),
        }

    async def terminate(self):
        """卸载时清理定时任务。"""
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("[floyd] 已停止，定时任务已清理")

    # ---------- 群消息：卡片识别 + 打卡 ----------
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群消息：缓存 umo；若是网易云分享则生成卡片并打卡。"""
        group_id = event.get_group_id() or ""

        # 缓存 umo（跨平台推送用），任何群消息都记一次。
        await scheduler_mod.remember_group_umo(self, group_id, event.unified_msg_origin)

        is_checkin_group = group_id in self.target_groups
        if not is_checkin_group:
            return

        song_id = self._extract_song_id_from_event(event)
        if not song_id:
            return

        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()
        logger.info(f"[floyd] 收到网易云分享：群={group_id} 用户={sender_name}({sender_id}) 歌曲id={song_id}")
        result = await card_service.generate_song_card(
            song_id,
            recommender=sender_name,
            recommender_qq=sender_id,
            output_dir=CARD_OUTPUT_DIR,
        )
        if not result:
            yield event.plain_result("歌曲卡片生成失败，可能歌曲已下架或网络异常。")
            return

        logger.info(f"[floyd] 卡片生成完成：{result['song'].get('name','?')} - {result['song'].get('artists','?')}")
        yield event.image_result(result["path"])

        # 卡片成功生成才算打卡。
        song = result["song"]
        is_new = await self.checkin_store.checkin(
            sender_id, sender_name,
            song=song.get("name", ""),
            artist=song.get("artists", ""),
            cover_url=song.get("cover_url", ""),
            song_id=song.get("id"),
            album=song.get("album", ""),
        )
        if not is_new:
            logger.info(f"[floyd] {sender_id} 今日已打卡，重复分享不累计")
        else:
            logger.info(f"[floyd] 打卡成功：{sender_name}({sender_id}) - 《{song.get('name','?')}》")

    def _extract_song_id_from_event(self, event: AstrMessageEvent) -> Optional[int]:
        """从消息组件里提取网易云歌曲 id（兼容 Json 卡片与纯文本 URL）。"""
        message = getattr(getattr(event, "message_obj", None), "message", None) or []
        blob_parts: list[str] = []
        for comp in message:
            # Comp.Json 的 data 可能是 dict 或 str。
            data = getattr(comp, "data", None)
            if isinstance(data, dict):
                blob_parts.append(json.dumps(data, ensure_ascii=False))
            elif isinstance(data, str):
                blob_parts.append(data)
            # 文本组件 / 其他组件的字符串形态兜底。
            blob_parts.append(str(comp))
        # 再补一层 message_str（部分适配器把链接放这里）。
        blob_parts.append(getattr(event, "message_str", "") or "")
        return extract_song_id("\n".join(blob_parts))

    # ---------- 指令 ----------
    @filter.command("forcepush")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def forcepush(self, event: AstrMessageEvent):
        """手动把当日推歌主题推送到目标群（管理员）。"""
        logger.info(f"[floyd] /forcepush 由 {event.get_sender_name()}({event.get_sender_id()}) 触发")
        cfg = self._scheduler_cfg()
        today = date.today()
        text: Optional[str]
        if cfg["challenge_mode"] == "daily_ai":
            day_number = (today - cfg["start_date"]).days + 1 if today >= cfg["start_date"] else 1
            t = await ai_generator.generate_daily(
                self.context, self.challenge_mgr,
                day_number=max(day_number, 1),
                gen_provider=cfg["gen_provider"],
                umo_fallback=await self.get_first_known_umo(),
            )
            text = f"🎵 今日推歌挑战 · Day {day_number}\n{t}" if t else None
        else:
            text = await scheduler_mod.build_push_text(self.challenge_mgr, start_date=cfg["start_date"], today=today)
        if not text:
            yield event.plain_result("今日暂无可推送的文案（请检查起算日或文案库）。")
            return

        groups = cfg["target_groups"]
        if not groups:
            yield event.plain_result(text)
            yield event.plain_result("（未配置 target_groups，已在此回复而非推送到群）")
            return

        sent_to, failed = [], []
        for g in groups:
            ok = await scheduler_mod.send_to_group(self, self.context, g, text)
            (sent_to if ok else failed).append(g)
        if sent_to:
            await scheduler_mod._mark_done(self, "push", today)
        parts = []
        if sent_to:
            parts.append(f"✅ 已推送到群：{', '.join(sent_to)}")
        if failed:
            parts.append(f"⚠️ 推送失败（未缓存 UMO？）：{', '.join(failed)}")
        yield event.plain_result("\n".join(parts))

    @filter.command("summary")
    async def summary(self, event: AstrMessageEvent):
        """手动查看当日打卡总结。"""
        logger.info(f"[floyd] /summary 由 {event.get_sender_name()} 触发")
        cfg = self._scheduler_cfg()
        if cfg.get("auto_summary_image"):
            today = date.today()
            today_data = await self.checkin_store.get_today_sorted(today)
            checkins = today_data.get("checkins", [])
            stats = await self.checkin_store.get_stats()
            image_path = await scheduler_mod._render_summary_card(self, today, checkins, stats)
            if image_path:
                logger.info(f"[floyd] /summary 发送图片：{image_path}")
                yield event.image_result(image_path)
                return
            logger.info("[floyd] /summary 图片渲染失败，回落纯文本")
        else:
            logger.info("[floyd] /summary auto_summary_image 关闭，发送纯文本")
        # 图片渲染失败或关闭时，回落纯文本
        yield event.plain_result(await scheduler_mod.build_summary_text(self.checkin_store))

    @filter.command("weekly")
    async def weekly(self, event: AstrMessageEvent):
        """手动查看本周打卡总结（默认近 7 天）。"""
        cfg = self._scheduler_cfg()
        if cfg.get("auto_summary_image"):
            image_path = await scheduler_mod.render_weekly_card(self)
            if image_path:
                yield event.image_result(image_path)
                return
        # 图片渲染失败或关闭时，回落纯文本
        yield event.plain_result(await scheduler_mod.build_weekly_text(self.checkin_store))

    @filter.command("streak")
    async def streak(self, event: AstrMessageEvent):
        """查看我的连续/总打卡天数。"""
        stat = await self.checkin_store.get_user_stat(event.get_sender_id())
        if not stat:
            yield event.plain_result("你还没有打卡记录，分享一首歌开始打卡吧 🎶")
            return
        yield event.plain_result(
            f"📊 {stat.get('name', event.get_sender_id())}\n"
            f"当前连续：{stat.get('streak', 0)} 天\n"
            f"最长连续：{stat.get('max_streak', 0)} 天\n"
            f"累计打卡：{stat.get('total', 0)} 次\n"
            f"最近打卡：{stat.get('last_date', '-')}"
        )

    @filter.command("rank")
    async def rank(self, event: AstrMessageEvent):
        """打卡排行榜（默认按总打卡数）。"""
        data = await self.checkin_store.get_rank(by="total", limit=10)
        rank = data.get("rank", [])
        if not rank:
            yield event.plain_result("还没有人打卡，快来成为第一个！")
            return
        lines = ["🏆 打卡排行榜（总打卡数）"]
        for i, u in enumerate(rank, 1):
            medal = "🥇🥈🥉"[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} {u.get('name', u.get('user_id', '?'))} — {u.get('total', 0)} 次")
        yield event.plain_result("\n".join(lines))
