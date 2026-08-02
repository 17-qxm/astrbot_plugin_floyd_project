"""AI 生成每日推歌挑战文案。

两种模式：
- ``batch``：一次性生成 N 条主题，写入文案库（WebUI 触发）。
- ``daily``：每日推歌时现生成一条（``challenge_mode = daily_ai`` 时由调度器调用）。

走 AstrBot 的 ``context.llm_generate``，provider 由配置项 ``gen_provider`` 指定；
若留空则回落到任意会话的当前 provider（取一个群会话作为载体）。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from astrbot.api import logger

import challenge as challenge_mod

DEFAULT_BATCH_PROMPT = (
    "你是一个音乐挑战策划。请生成 {count} 条「每日推歌挑战」主题文案，"
    "每条一句话、有创意、能激发分享欲（可以涉及心情、场景、年代、歌名元素等，风格多样）。"
    "只输出文案，每行一条，不要编号、不要解释、不要前后缀。"
)

DEFAULT_DAILY_PROMPT = (
    "今天是第 {day} 天推歌挑战。请生成今天的主题，一句话，有创意、能激发分享欲。"
    "只输出主题本身，不要编号、不要引号、不要解释。"
)

# 清洗 LLM 输出：去编号前缀、去空行、去首尾引号/空白。
_LEADING_NUM = re.compile(r"^\s*(?:Day\s*\d+|第\s*\d+\s*天|\d+[\.\)、\-])\s*", re.IGNORECASE)


def _clean_line(line: str) -> str:
    line = _LEADING_NUM.sub("", line).strip()
    if len(line) >= 2 and line[0] in "\"'“”‘’ " and line[-1] in "\"'“”‘’ ":
        line = line[1:-1].strip()
    return line


def parse_lines(text: str) -> list[str]:
    """把 LLM 整段输出拆成干净的多条文案，跳过空行。"""
    return [c for c in (_clean_line(ln) for ln in (text or "").splitlines()) if c]


async def _resolve_provider(context: Any, gen_provider: str, umo_fallback: str) -> Optional[str]:
    """确定使用哪个 provider：优先配置项，否则回落到 fallback 会话的当前 provider。"""
    if gen_provider:
        return gen_provider
    if umo_fallback:
        try:
            return await context.get_current_chat_provider_id(umo_fallback)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ai_generator] 获取当前 provider 失败: {e}")
    return None


async def generate_batch(
    context: Any,
    manager: challenge_mod.ChallengeManager,
    *,
    count: int = 10,
    custom_prompt: Optional[str] = None,
    gen_provider: str = "",
    umo_fallback: str = "",
) -> dict:
    """批量生成文案并追加入库。返回 ``{"added": N, "provider": "...", "raw": "..."}``。"""
    if count <= 0 or count > 100:
        raise ValueError("count 应在 1..100 之间")

    provider = await _resolve_provider(context, gen_provider, umo_fallback)
    if not provider:
        raise RuntimeError("未配置 gen_provider 且无法回落到当前会话 provider")

    prompt = (custom_prompt or DEFAULT_BATCH_PROMPT).format(count=count)
    logger.info(f"[ai_generator] 批量生成 {count} 条，provider={provider}")
    resp = await context.llm_generate(provider, prompt)
    raw = getattr(resp, "completion_text", None) or str(resp)
    lines = parse_lines(raw)[:count]
    added = manager.add_many(lines, source=challenge_mod.SOURCE_AI)
    logger.info(f"[ai_generator] 生成完成，入库 {added} 条")
    return {"added": added, "provider": provider, "raw": raw}


async def generate_daily(
    context: Any,
    manager: challenge_mod.ChallengeManager,
    *,
    day_number: int,
    custom_prompt: Optional[str] = None,
    gen_provider: str = "",
    umo_fallback: str = "",
) -> Optional[str]:
    """每日现生成一条主题并追加存档，返回文案文本。失败返回 None。"""
    provider = await _resolve_provider(context, gen_provider, umo_fallback)
    if not provider:
        logger.warning("[ai_generator] daily 模式无可用 provider，跳过生成")
        return None
    prompt = (custom_prompt or DEFAULT_DAILY_PROMPT).format(day=day_number)
    try:
        resp = await context.llm_generate(provider, prompt)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ai_generator] 每日生成失败: {e}")
        return None
    raw = getattr(resp, "completion_text", None) or str(resp)
    lines = parse_lines(raw)
    if not lines:
        return None
    text = lines[0]
    manager.add(text, source=challenge_mod.SOURCE_AI)
    return text
