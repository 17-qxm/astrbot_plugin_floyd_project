"""用户头像获取（QQ 官方机器人平台）。

获取顺序：
1. **事件下发头像 URL**：自 2026-11-16 官方变更起，群消息事件 author 直接携带
   ``avatar`` 字段（同时新增 ``member_nickname`` 群内昵称），直接下载。
2. **thirdqq.qlogo.cn API 兜底**：``https://thirdqq.qlogo.cn/qqapp/{appid}/{openid}/{size}``
   AppID 运行时从 qq_official 平台适配器读取；openid 即事件里的 member_openid。

旧链路已删除：``q.qlogo.cn/headimg_dl?dst_uin=<QQ号>`` 只认真实数字 QQ 号，
qq_official 下 sender_id 是 member_openid，该链路对官方机器人无效。

失败模式（2026-11-18 实测）：thirdqq 端点对无效 openid/appid 组合**不报错**，
返回 200 + 恒定 1512 字节的默认企鹅图；真实头像 36KB 起。
因此按字节量阈值过滤默认图，小于阈值视为失败，让渲染层走首字母占位圆。
"""

from __future__ import annotations

from typing import Any, Optional

import aiohttp

from astrbot.api import logger

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# 默认企鹅头像实测恒为 1512B；真实头像 36KB+。低于 2.5KB 一律视为默认图。
_MIN_VALID_BYTES = 2500
_THIRDQQ_SIZE = 640


async def _get_bytes(url: str, *, timeout: int = 10) -> bytes:
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            return await resp.read()


def get_qqofficial_appid(context: Any) -> str:
    """运行时读取 qq_official 平台适配器的 AppID；无该平台返回空串。"""
    try:
        for platform in context.platform_manager.platform_insts:
            if platform.meta().name == "qq_official":
                return str(getattr(platform, "appid", "") or "")
    except Exception as e:  # noqa: BLE001
        logger.info(f"[avatar] 读取 qq_official AppID 失败: {e}")
    return ""


def extract_event_author(event: Any) -> dict:
    """从群消息事件的原始 payload 提取 author 字典。

    qq_official 适配器把 botpy message 挂在 ``event.message_obj.raw_message``，
    其 ``raw_data`` 保留完整事件体；author 含
    ``avatar``（头像 URL）/ ``member_nickname``（群昵称）/ ``username`` / ``member_openid``。
    非 qq_official 平台返回空 dict。
    """
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    data = getattr(raw, "raw_data", None)
    if isinstance(data, dict):
        author = data.get("author")
        if isinstance(author, dict):
            return author
    return {}


async def fetch_user_avatar(
    *,
    avatar_url: str = "",
    openid: str = "",
    appid: str = "",
    timeout: int = 10,
) -> Optional[bytes]:
    """获取头像字节：事件 URL 优先 → thirdqq API 兜底 → 全失败返回 None。

    Args:
        avatar_url: 事件 author.avatar 下发的头像 URL（最优来源）。
        openid: 成员 openid（qq_official 的 sender_id），thirdqq 兜底用。
        appid: 机器人 AppID，thirdqq 兜底用；与 openid 必须同属一个机器人应用。
        timeout: 单次请求超时秒数。

    Returns:
        头像图片字节；不可得 / 为默认图时返回 None（渲染层走占位）。
    """
    # ① 事件下发头像 URL（最优：官方直出，无需拼参数）
    if avatar_url:
        try:
            data = await _get_bytes(avatar_url, timeout=timeout)
            if len(data) >= _MIN_VALID_BYTES:
                return data
            logger.info(f"[avatar] 事件头像过小（{len(data)}B），疑似默认图，尝试兜底")
        except Exception as e:  # noqa: BLE001
            logger.info(f"[avatar] 事件头像下载失败: {e}")

    # ② thirdqq.qlogo.cn API 兜底（AppID + member_openid）
    if appid and openid:
        url = f"https://thirdqq.qlogo.cn/qqapp/{appid}/{openid}/{_THIRDQQ_SIZE}"
        try:
            data = await _get_bytes(url, timeout=timeout)
            if len(data) >= _MIN_VALID_BYTES:
                return data
            logger.info(f"[avatar] thirdqq 返回默认图（{len(data)}B），放弃头像")
        except Exception as e:  # noqa: BLE001
            logger.info(f"[avatar] thirdqq 头像下载失败: {e}")

    return None
