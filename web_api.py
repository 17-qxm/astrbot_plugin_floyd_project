"""WebUI 后端路由（Quart）。

通过 ``context.register_web_api`` 注册，路由前缀必须为插件名。
前端 ``bridge.apiGet("challenges")`` → ``/api/plug/<plugin>/challenges``。

所有 handler 都是 ``async def``，返回 Quart response（``jsonify`` / ``send_file``）。
依赖 main.py 在 ``__init__`` 里把插件实例传入。
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

from quart import jsonify, request, send_file

import ai_generator
import challenge as challenge_mod
import checkin as checkin_mod
from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_floyd_project"


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _ok(data: Any = None):
    return jsonify({"ok": True, "data": data})


class WebAPI:
    """持有插件引用，提供所有 WebAPI handler 方法。

    在 main.py 里调用 :meth:`register_all` 完成全部路由注册。
    """

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.context = plugin.context
        self.manager: challenge_mod.ChallengeManager = plugin.challenge_mgr
        self.store: checkin_mod.CheckinStore = plugin.checkin_store

    # ---- 注册 ----
    def register_all(self) -> None:
        reg = self.context.register_web_api
        prefix = f"/{PLUGIN_NAME}"

        reg(f"{prefix}/challenges", self.challenges_list, ["GET"], "列出推歌文案")
        reg(f"{prefix}/challenges", self.challenges_create, ["POST"], "新增推歌文案")
        reg(f"{prefix}/challenges/import", self.challenges_import, ["POST"], "批量导入文案")
        reg(f"{prefix}/challenges/export", self.challenges_export, ["GET"], "导出文案 txt")
        reg(f"{prefix}/challenges/generate", self.challenges_generate, ["POST"], "AI 生成文案")
        reg(f"{prefix}/checkin/today", self.checkin_today, ["GET"], "今日打卡")
        reg(f"{prefix}/checkin/stats", self.checkin_stats, ["GET"], "打卡统计")
        reg(f"{prefix}/checkin/history", self.checkin_history, ["GET"], "打卡历史(热力图)")
        reg(f"{prefix}/checkin/rank", self.checkin_rank, ["GET"], "打卡排行榜")
        reg(f"{prefix}/checkin/rebuild", self.checkin_rebuild, ["POST"], "重算统计")
        reg(f"{prefix}/state", self.state, ["GET"], "插件状态总览")

    # ---------- 挑战文案 ----------
    async def challenges_list(self):
        return _ok(self.manager.list_all())

    async def challenges_create(self):
        body = await request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return _err("text 不能为空")
        source = body.get("source") or challenge_mod.SOURCE_MANUAL
        return _ok(self.manager.add(text, source=source))

    async def challenges_import(self):
        """批量导入：body 形如 {texts:[...]} 或 {raw:"多行文本", mode:"append|replace"}。"""
        body = await request.get_json(silent=True) or {}
        mode = body.get("mode", "append")
        raw = body.get("raw", "")
        texts = body.get("texts")
        if texts is None:
            texts = raw.splitlines()
        if mode == "replace":
            n = self.manager.replace_all(texts, source=challenge_mod.SOURCE_IMPORT)
        else:
            n = self.manager.add_many(texts, source=challenge_mod.SOURCE_IMPORT)
        return _ok({"affected": n, "total": self.manager.count()})

    async def challenges_export(self):
        text = self.manager.export_text()
        buf = io.BytesIO(text.encode("utf-8"))
        buf.seek(0)
        return await send_file(
            buf,
            mimetype="text/plain",
            as_attachment=True,
            download_name="challenges.txt",
        )

    async def challenges_generate(self):
        """AI 批量生成。body: {count?:10, prompt?, provider?}"""
        body = await request.get_json(silent=True) or {}
        count = int(body.get("count", 10))
        custom_prompt = body.get("prompt")
        gen_provider = body.get("provider") or self.plugin.config.get("gen_provider", "")
        umo_fb = await self.plugin.get_first_known_umo()
        try:
            result = await ai_generator.generate_batch(
                self.context, self.manager,
                count=count,
                custom_prompt=custom_prompt,
                gen_provider=gen_provider,
                umo_fallback=umo_fb,
            )
        except (ValueError, RuntimeError) as e:
            return _err(str(e), 500)
        return _ok(result)

    # ---------- 打卡 ----------
    async def checkin_today(self):
        return _ok(await self.store.get_today())

    async def checkin_stats(self):
        return _ok(await self.store.get_stats())

    async def checkin_history(self):
        """默认查最近 90 天。?from=YYYY-MM-DD&to=YYYY-MM-DD。"""
        today = date.today()
        date_from = request.args.get("from")
        date_to = request.args.get("to") or today.isoformat()
        try:
            d_to = date.fromisoformat(date_to)
            d_from = date.fromisoformat(date_from) if date_from else d_to - timedelta(days=89)
        except ValueError:
            return _err("日期格式应为 YYYY-MM-DD")
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        return _ok(await self.store.get_history(d_from, d_to))

    async def checkin_rank(self):
        by = request.args.get("by", "total")
        if by not in ("total", "streak", "max_streak"):
            by = "total"
        limit = int(request.args.get("limit", 20))
        return _ok(await self.store.get_rank(by=by, limit=limit))

    async def checkin_rebuild(self):
        return _ok(await self.store.rebuild_stats())

    # ---------- 状态 ----------
    async def state(self):
        cfg = self.plugin.config
        return _ok({
            "challenge_count": self.manager.count(),
            "challenge_mode": cfg.get("challenge_mode", "sequential"),
            "push_time": cfg.get("push_time", "08:00"),
            "summary_time": cfg.get("summary_time", "22:00"),
            "target_groups": cfg.get("target_groups", []),
            "server_time": datetime.now().isoformat(timespec="seconds"),
        })


def register_delete_route(plugin: Any) -> None:
    """单独注册 DELETE /challenges/<idx>。

    register_web_api 不直接支持路径参数，这里把 idx 解析放在 handler 里，
    通过 query string 传递（前端 ``apiDelete('challenges', {idx})`` 或 DELETE ?idx=）。
    为兼容 bridge 的 apiGet/apiPost 风格，提供 ``challenges_delete`` 端点。
    """
    async def handler():
        idx = request.args.get("idx")
        if not idx:
            try:
                body = await request.get_json(silent=True) or {}
                idx = body.get("idx")
            except Exception:  # noqa: BLE001
                idx = None
        if not idx:
            return _err("缺少 idx")
        try:
            idx_i = int(idx)
        except ValueError:
            return _err("idx 必须是整数")
        ok = plugin.challenge_mgr.delete(idx_i)
        return _ok({"deleted": ok}) if ok else _err("idx 不存在", 404)

    plugin.context.register_web_api(
        f"/{PLUGIN_NAME}/challenges/delete", handler, ["POST", "DELETE"], "删除推歌文案"
    )
