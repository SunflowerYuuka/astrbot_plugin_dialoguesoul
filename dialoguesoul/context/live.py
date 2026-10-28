from __future__ import annotations

import asyncio
import inspect

from .. import config as cfg
from ..interest import InterestJudge
from .forwards import ForwardRenderer, fetch_forward_payload
from .images import CaptionService
from .summary import SummaryService


def aux_timeout(config) -> float:
    try:
        return float(cfg.get(config, "decision.aux_timeout_seconds", 15) or 0)
    except (TypeError, ValueError):
        return 15.0


async def _call_with_timeout(call, timeout: float):
    if timeout > 0:
        return await asyncio.wait_for(call, timeout=timeout)
    return await call


async def _provider(context, umo: str, provider_id: str):
    provider = None
    if provider_id and hasattr(context, "get_provider_by_id"):
        provider = context.get_provider_by_id(provider_id)
    if provider is None and hasattr(context, "get_using_provider"):
        provider = context.get_using_provider(umo=umo)
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
            aux_timeout(config),
        )
        return (getattr(response, "completion_text", "") or "").strip()

    return CaptionService(
        captioner,
        concurrency=cfg.get(config, "context.image_caption.concurrency", 3),
        cache_size=cfg.get(config, "context.image_caption.cache_size", 128),
    )


def build_forward_renderer(event, config):
    if not cfg.get(config, "context.forward.parse", False):
        return None

    async def fetcher(forward_id: str):
        return await fetch_forward_payload(event, forward_id)

    return ForwardRenderer(
        fetcher,
        max_depth=cfg.get(config, "context.forward.max_depth", 2),
        max_nodes=cfg.get(config, "context.forward.max_nodes", 50),
        max_chars=cfg.get(config, "context.forward.max_chars", 2000),
        timeout=cfg.get(config, "context.forward.timeout", 5),
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
            aux_timeout(config),
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

    return InterestJudge(resolver, prompt, timeout=aux_timeout(config))


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
        timeout=aux_timeout(config),
    )
