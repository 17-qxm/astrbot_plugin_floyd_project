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
        reg(f"{prefix}/checkin/today", self.checkin_today, ["GET"], "今日打卡")
        reg(f"{prefix}/checkin/stats", self.checkin_stats, ["GET"], "打卡统计")
        reg(f"{prefix}/checkin/history", self.checkin_history, ["GET"], "打卡历史(热力图)")
        reg(f"{prefix}/checkin/rank", self.checkin_rank, ["GET"], "打卡排行榜")
        reg(f"{prefix}/checkin/rebuild", self.checkin_rebuild, ["POST"], "重算统计")
        reg(f"{prefix}/state", self.state, ["GET"], "插件状态总览")
        reg(f"{prefix}/config", self.config_get, ["GET"], "获取插件配置")
        reg(f"{prefix}/config", self.config_save, ["POST"], "保存插件配置")

    # ---------- 挑战文案 ----------
    async def challenges_list(self):
        return _ok(self.manager.list_all())

    async def challenges_create(self):
        body = await request.get_json(silent=True) or {}
        # 带 idx 走更新，不带走新增
        if body.get("idx") is not None:
            return await self.challenges_update(body)
        text = (body.get("text") or "").strip()
        if not text:
            return _err("text 不能为空")
        source = body.get("source") or challenge_mod.SOURCE_MANUAL
        return _ok(self.manager.add(text, source=source))

    async def challenges_update(self, body=None):
        """更新指定 idx 的文案。body: {idx, text}"""
        body = body if body is not None else (await request.get_json(silent=True) or {})
        try:
            idx = int(body.get("idx"))
        except (TypeError, ValueError):
            return _err("idx 必须是整数")
        text = (body.get("text") or "").strip()
        if not text:
            return _err("text 不能为空")
        res = self.manager.update(idx, text)
        return _ok(res) if res else _err("idx 不存在", 404)

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
            "weekly_time": cfg.get("weekly_time", "22:30"),
            "weekly_day": int(cfg.get("weekly_day", 7) or 7),
            "challenge_start_date": cfg.get("challenge_start_date", ""),
            "auto_summary_image": bool(cfg.get("auto_summary_image", True)),
            "target_groups": cfg.get("target_groups", []),
            "server_time": datetime.now().isoformat(timespec="seconds"),
        })

    # ---------- 配置 ----------
    async def config_get(self):
        """返回 schema + 当前值，前端据此渲染配置表单。"""
        cfg = self.plugin.config
        schema = getattr(cfg, "schema", None) or {}
        # 过滤掉 AstrBotConfig 内部字段，只返回业务键。
        values = {k: cfg.get(k) for k in (schema or {}) if not k.startswith("_")}
        return _ok({"schema": schema, "values": values})

    async def config_save(self):
        """部分更新配置。save 后不自动 reload，前端提示用户手动重载。"""
        body = await request.get_json(silent=True) or {}
        cfg = self.plugin.config
        # 只允许更新 schema 里声明的键，防越权写。
        schema = getattr(cfg, "schema", None) or {}
        allowed = {k: v for k, v in body.items() if k in schema and not k.startswith("_")}
        if not allowed:
            return _err("没有可更新的配置项")
        try:
            await cfg.save_config_async(allowed)
        except Exception as e:  # noqa: BLE001
            logger.info(f"[web_api] 配置保存失败: {e}")
            return _err(f"保存失败: {e}", 500)
        logger.info(f"[web_api] 配置已保存：{list(allowed.keys())}（需重载插件生效定时任务变更）")
        return _ok({"saved": list(allowed.keys()), "hint": "配置已写入，需在 Dashboard 重载插件后生效定时任务变更"})


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
