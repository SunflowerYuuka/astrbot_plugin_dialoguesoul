from __future__ import annotations

import asyncio
import inspect

from .. import config as cfg
from ..interest import InterestJudge
from .forwards import ForwardRenderer, fetch_forward_payload
from .images import CaptionService
from .summary import SummaryService


AUX_TIMEOUT_DEFAULT = 45.0


def _as_seconds(value, fallback: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, seconds)


def aux_timeout(config, path: str = "") -> float:
    """辅助模型调用的超时（秒），0 表示不限。

    `path` 指向某个辅助功能自己的 `timeout_seconds`；该值为 0 或未配置时
    回退到全局的 `decision.aux_timeout_seconds`。
    """
    if path:
        own = _as_seconds(cfg.get(config, path, 0), 0.0)
        if own > 0:
            return own
    return _as_seconds(
        cfg.get(config, "decision.aux_timeout_seconds", AUX_TIMEOUT_DEFAULT),
        AUX_TIMEOUT_DEFAULT,
    )


async def _call_with_timeout(call, timeout: float):
    if timeout > 0:
        return await asyncio.wait_for(call, timeout=timeout)
    return await call


async def _provider(context, umo: str, provider_id: str):
    provider = None
    if provider_id:
        getter = getattr(context, "get_provider_by_id", None)
        if callable(getter):
            provider = getter(provider_id)
    if provider is None:
        # get_using_provider 已弃用，优先使用异步版本
        getter = getattr(context, "get_using_provider_async", None)
        if callable(getter):
            provider = getter(umo=umo)
    if provider is None:
        getter = getattr(context, "get_using_provider", None)
        if callable(getter):
            provider = getter(umo=umo)
    if inspect.isawaitable(provider):
        provider = await provider
    return provider


def build_caption_service(context, config):
    if not cfg.get(config, "context.image_caption.enabled", False):
        return None

    async def captioner(umo: str, url: str) -> str:
        provider = await _provider(
            context, umo, cfg.get(config, "context.image_caption.provider_id", "")
        )
        if provider is None:
            return ""
        response = await _call_with_timeout(
            provider.text_chat(
                prompt=cfg.get(
                    config, "context.image_caption.prompt", "请直接简短描述这张图片"
                ),
                image_urls=[url],
            ),
            aux_timeout(config, "context.image_caption.timeout_seconds"),
        )
        return (getattr(response, "completion_text", "") or "").strip()

    return CaptionService(
        captioner,
        concurrency=cfg.get(config, "context.image_caption.concurrency", 3),
        cache_size=cfg.get(config, "context.image_caption.cache_size", 128),
    )


def build_forward_renderer(event, config, caption_service=None):
    """按配置构建转发渲染器。

    `context.forward.parse` 控制当前消息里的转发是否展开；
    `context.forward.history_messages` 控制历史里的转发是否展开。
    两者都为 0/关闭时返回 None。
    """
    parse = bool(cfg.get(config, "context.forward.parse", False))
    try:
        history_window = int(
            cfg.get(config, "context.forward.history_messages", 0) or 0
        )
    except (TypeError, ValueError):
        history_window = 0
    if not parse and history_window <= 0:
        return None

    async def fetcher(forward_id: str):
        return await fetch_forward_payload(event, forward_id)

    captioner = None
    if caption_service is not None and cfg.get(
        config, "context.forward.caption_images", False
    ):
        umo = getattr(event, "unified_msg_origin", "")

        async def captioner(urls, _umo=umo):
            return await caption_service.caption(urls, umo=_umo)

    return ForwardRenderer(
        fetcher,
        max_depth=cfg.get(config, "context.forward.max_depth", 2),
        max_nodes=cfg.get(config, "context.forward.max_nodes", 50),
        max_chars=cfg.get(config, "context.forward.max_chars", 2000),
        timeout=cfg.get(config, "context.forward.timeout", 5),
        captioner=captioner,
    )


def build_summary_service(context, config):
    if not cfg.get(config, "context.summary.enabled", False):
        return None

    async def summarizer(umo, fallback):
        provider = await _provider(
            context, umo, cfg.get(config, "context.summary.provider_id", "")
        )
        if provider is None:
            return fallback
        response = await _call_with_timeout(
            provider.text_chat(
                prompt="请把以下群聊记录压缩成简要摘要，保留人物、话题和结论：\n"
                + fallback,
                system_prompt="只输出摘要正文。",
            ),
            aux_timeout(config, "context.summary.timeout_seconds"),
        )
        return (getattr(response, "completion_text", "") or "").strip() or fallback

    return SummaryService(
        summarizer,
        threshold=int(cfg.get(config, "context.summary.threshold", 20)),
    )


def build_intervention_judge(context, config):
    if not cfg.get(config, "extra_prompt.enabled", False):
        return None

    criteria = str(cfg.get(config, "extra_prompt.text", "") or "").strip()
    if not criteria:
        criteria = "判断当前聊天是否值得你介入。"
    prompt = (
        f"{criteria}\n\n"
        "请结合最近聊天记录和当前消息，判断是否应该介入。只输出 YES 或 NO。"
    )

    async def resolver(event):
        return await _provider(
            context,
            event.unified_msg_origin,
            cfg.get(config, "extra_prompt.provider_id", ""),
        )

    return InterestJudge(
        resolver,
        prompt,
        timeout=aux_timeout(config, "extra_prompt.timeout_seconds"),
        name="附加提示词判断",
    )


def build_interest_judge(context, config):
    if cfg.get(config, "trigger.strategy", "window") != "interest":
        return None
    if not cfg.get(config, "trigger.interest.enabled", True):
        return None

    async def resolver(event):
        return await _provider(
            context,
            event.unified_msg_origin,
            cfg.get(config, "trigger.interest.provider_id", ""),
        )

    return InterestJudge(
        resolver,
        "判断这条群聊消息是否值得你像群友一样接话。只输出 YES 或 NO。",
        timeout=aux_timeout(config, "trigger.interest.timeout_seconds"),
        name="兴趣判断",
    )
