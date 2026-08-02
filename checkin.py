"""打卡记录与统计。

数据通过 AstrBot KV 存储持久化（隔离、自动落盘）。两份主数据：

- ``checkin:by_date`` → ``{ "<YYYY-MM-DD>": { <sender_id>: {name, song, artist, time} } }``
- ``checkin:stats``    → ``{ <sender_id>: {name, total, streak, last_date, max_streak} }``

打卡规则：分享并成功生成卡片才算一次，每人每天最多计一次。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Optional

from astrbot.api import logger

KEY_BY_DATE = "checkin:by_date"
KEY_STATS = "checkin:stats"


class CheckinStore:
    """封装 KV 读写与统计计算。所有方法都是 async（依赖 KV 接口）。

    通过注入 ``plugin``（Star 子类实例）获得 ``get/put_kv_data`` 能力。
    用一把 asyncio 锁串行化写操作，避免并发打卡产生覆盖。
    """

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self._lock = asyncio.Lock()

    # ---- 底层 KV 读写 ----
    async def _get(self, key: str, default: Any) -> Any:
        return await self.plugin.get_kv_data(key, default)

    async def _set(self, key: str, value: Any) -> None:
        await self.plugin.put_kv_data(key, value)

    # ---- 打卡写入 ----
    async def checkin(
        self,
        sender_id: str,
        sender_name: str,
        *,
        song: str,
        artist: str,
        cover_url: str = "",
        song_id: Optional[int] = None,
        album: str = "",
        today: Optional[date] = None,
    ) -> bool:
        """记录一次打卡。每人每天最多一次，重复返回 False。

        Args:
            song / artist / cover_url / song_id / album: 本次分享的歌曲信息。
            cover_url 用于每日总结里的封面模糊背景。
        Returns:
            本次是否为新打卡（True）或当天已打过（False）。
        """
        today = today or date.today()
        today_str = today.isoformat()
        async with self._lock:
            by_date = await self._get(KEY_BY_DATE, {}) or {}
            day = by_date.get(today_str, {})
            is_new = sender_id not in day
            day[sender_id] = {
                "uid": sender_id,
                "name": sender_name,
                "song": song,
                "artist": artist,
                "cover_url": cover_url or "",
                "song_id": song_id,
                "album": album or "",
                "time": datetime.now().strftime("%H:%M"),
            }
            by_date[today_str] = day
            await self._set(KEY_BY_DATE, by_date)

            # 同步刷新统计
            stats = await self._get(KEY_STATS, {}) or {}
            await self._set(KEY_STATS, self._recompute_one(stats, sender_id, sender_name, today_str))
        return is_new

    @staticmethod
    def _recompute_one(
        stats: dict, sender_id: str, sender_name: str, today_str: str
    ) -> dict:
        """根据 last_date 增量更新 streak / total / max_streak。"""
        prev = stats.get(sender_id, {})
        last_date_str = prev.get("last_date")
        if last_date_str:
            try:
                last = date.fromisoformat(last_date_str)
                today = date.fromisoformat(today_str)
                gap = (today - last).days
            except ValueError:
                gap = None

        # 判断连续性
        if not last_date_str:
            streak = 1
        elif gap == 1:
            streak = int(prev.get("streak", 0)) + 1
        elif gap == 0:
            # 同一天重复（理论上 is_new 已为 False，这里防御性处理）
            streak = int(prev.get("streak", 1))
        else:
            streak = 1  # 断签

        total = int(prev.get("total", 0)) + 1
        max_streak = max(int(prev.get("max_streak", 0)), streak)
        stats[sender_id] = {
            "name": sender_name,
            "total": total,
            "streak": streak,
            "max_streak": max_streak,
            "last_date": today_str,
        }
        return stats

    # ---- 查询 ----
    async def get_today(self, today: Optional[date] = None) -> dict:
        today_str = (today or date.today()).isoformat()
        by_date = await self._get(KEY_BY_DATE, {}) or {}
        return {"date": today_str, "checkins": by_date.get(today_str, {})}

    async def get_today_sorted(self, today: Optional[date] = None) -> dict:
        """今日打卡，按打卡时间升序排列（早 → 晚）。"""
        data = await self.get_today(today)
        checkins = data["checkins"]
        ordered = sorted(
            checkins.items(),
            key=lambda kv: (kv[1].get("time", "99:99"), kv[0]),
        )
        data["checkins"] = [v for _, v in ordered]
        return data

    async def get_week(self, end: Optional[date] = None) -> dict:
        """返回 end 往前 7 天（含 end）的聚合数据，供每周总结用。

        每天保留按时间排序的打卡列表（含封面 URL），并附周统计。
        """
        end = end or date.today()
        start = end - timedelta(days=6)
        by_date = await self._get(KEY_BY_DATE, {}) or {}
        days: list[dict] = []
        total_checkins = 0
        participants: set[str] = set()
        cur = start
        while cur <= end:
            day_raw = by_date.get(cur.isoformat(), {})
            ordered = sorted(
                day_raw.items(),
                key=lambda kv: (kv[1].get("time", "99:99"), kv[0]),
            )
            items = [v for _, v in ordered]
            participants.update(uid for uid, _ in ordered)
            total_checkins += len(items)
            days.append({
                "date": cur.isoformat(),
                "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][cur.weekday()],
                "count": len(items),
                "checkins": items,
            })
            cur += timedelta(days=1)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "total_checkins": total_checkins,
            "participants": len(participants),
        }

    async def get_history(self, date_from: date, date_to: date) -> dict:
        """返回 [date_from, date_to] 闭区间内每天的打卡 uid 列表（热力图用）。"""
        by_date = await self._get(KEY_BY_DATE, {}) or {}
        out: dict[str, list[str]] = {}
        cur = date_from
        while cur <= date_to:
            day = by_date.get(cur.isoformat(), {})
            out[cur.isoformat()] = list(day.keys())
            cur += timedelta(days=1)
        return {"from": date_from.isoformat(), "to": date_to.isoformat(), "days": out}

    async def get_stats(self) -> dict:
        stats = await self._get(KEY_STATS, {}) or {}
        return {"users": stats}

    async def get_user_stat(self, sender_id: str) -> Optional[dict]:
        stats = await self._get(KEY_STATS, {}) or {}
        return stats.get(sender_id)

    async def get_rank(self, *, by: str = "total", limit: int = 20) -> dict:
        """排行榜。by 可选 ``total``(总打卡) 或 ``streak``(当前连续)。"""
        stats = await self._get(KEY_STATS, {}) or {}
        items = [
            {"user_id": uid, **info}
            for uid, info in stats.items()
        ]
        items.sort(key=lambda x: x.get(by, 0), reverse=True)
        return {"by": by, "rank": items[:limit]}

    # ---- 重算（用于数据自愈） ----
    async def rebuild_stats(self) -> dict:
        """根据 by_date 全量重算 stats（WebUI 维护/数据自愈用）。"""
        async with self._lock:
            by_date = await self._get(KEY_BY_DATE, {}) or {}
            stats: dict[str, dict] = {}
            for day_str in sorted(by_date.keys()):
                day = by_date[day_str] or {}
                # 当天每人各计一次
                day_counts: dict[str, int] = {}
                for uid, info in day.items():
                    day_counts[uid] = day_counts.get(uid, 0) + 1
                for uid, info in day.items():
                    name = info.get("name", uid)
                    # 该天计入 1 次（即便 day_counts>1 也按 1 算，符合每天最多 1 次）
                    stats = self._recompute_one(stats, uid, name, day_str)
                    # 修正 total：recompute_one 默认 +1，符合「按天计 1」
            await self._set(KEY_STATS, stats)
        return {"users": len(stats)}
