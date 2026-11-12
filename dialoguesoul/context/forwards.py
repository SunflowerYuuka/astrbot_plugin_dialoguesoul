from __future__ import annotations

import asyncio
import inspect

_ACTION = "get_forward_msg"


def _api_target(event):
    bot = getattr(event, "bot", None)
    api = getattr(bot, "api", None)
    call_action = getattr(api, "call_action", None) if api is not None else None
    if not callable(call_action):
        call_action = getattr(bot, "call_action", None)
    if callable(call_action):
        return "action", call_action
    call_api = getattr(event, "call_api", None)
    if callable(call_api):
        return "event", call_api
    return None, None


async def fetch_forward_payload(event, forward_id) -> dict:
    """Fetch a merged-forward payload through the OneBot action API."""
    kind, call = _api_target(event)
    if call is None:
        return {}
    forward_id = str(forward_id).strip()
    if not forward_id:
        return {}

    variants = []
    for key in ("message_id", "id", "forward_id"):
        variants.append({key: forward_id})
        if forward_id.isdigit():
            variants.append({key: int(forward_id)})

    for params in variants:
        try:
            if kind == "action":
                result = call(_ACTION, **params)
            else:
                result = call(_ACTION, params)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                return result
        except TypeError:
            continue
        except Exception:
            continue

    api = getattr(getattr(event, "bot", None), "api", None)
    getter = getattr(api, _ACTION, None) if api is not None else None
    if callable(getter):
        for params in variants:
            try:
                result = getter(**params)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict):
                    return result
            except Exception:
                continue
    return {}


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _content(item) -> list:
    if not isinstance(item, dict):
        return []
    content = item.get("content")
    if isinstance(content, list):
        return content
    data = _as_dict(item.get("data"))
    content = data.get("content")
    return content if isinstance(content, list) else []


def _segment_type(segment) -> str:
    raw = _as_dict(segment).get("type")
    if raw is None:
        raw = _as_dict(_as_dict(segment).get("data")).get("type")
    value = getattr(raw, "value", raw)
    return str(value or "").strip().lower()


def _image_source(segment) -> str:
    """取出图片段落的可下载地址，供转述使用。"""
    segment = _as_dict(segment)
    data = _as_dict(segment.get("data"))
    for source in (data, segment):
        for name in ("url", "file", "path"):
            value = source.get(name)
            if value:
                return str(value)
    return ""


def _segment_text(segment, captions=None) -> str:
    segment = _as_dict(segment)
    data = _as_dict(segment.get("data"))
    kind = _segment_type(segment)
    if kind in ("text", "plain"):
        return str(segment.get("text", data.get("text", "")))
    if kind == "image":
        caption = ""
        if captions:
            caption = str(captions.get(_image_source(segment), "") or "").strip()
        return f"[图片:{caption}]" if caption else "[图片]"
    if kind == "at":
        return f"@{data.get('qq') or segment.get('qq') or ''}"
    if kind == "face":
        return "[表情]"
    if kind == "record":
        return "[语音]"
    if kind == "video":
        return "[视频]"
    if kind == "file":
        return f"[文件:{data.get('name') or segment.get('name') or ''}]"
    if kind == "json":
        return "[JSON消息]"
    return f"[{kind}]" if kind else ""


def _sender_name(item) -> str:
    item = _as_dict(item)
    sender = _as_dict(item.get("sender"))
    data = _as_dict(item.get("data"))
    name = (
        sender.get("nickname")
        or sender.get("card")
        or item.get("name")
        or item.get("nickname")
        or data.get("nickname")
        or data.get("name")
        or "未知"
    )
    return str(name)


def _messages_from_payload(payload) -> list:
    if isinstance(payload, list):
        return payload
    payload = _as_dict(payload)
    messages = payload.get("messages")
    if isinstance(messages, list):
        return messages
    data = _as_dict(payload.get("data"))
    messages = data.get("messages")
    return messages if isinstance(messages, list) else []


class ForwardRenderer:
    """把合并转发内容压缩成纯文本。"""

    def __init__(
        self,
        fetcher,
        max_depth: int = 2,
        max_nodes: int = 50,
        max_chars: int = 2000,
        timeout: float = 5,
        captioner=None,
    ):
        self.fetcher = fetcher
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_chars = max_chars
        self.timeout = timeout
        self.captioner = captioner

    def _line(self, item, captions=None) -> str:
        text = "".join(_segment_text(segment, captions) for segment in _content(item))
        return f"{_sender_name(item)}: {text}"

    def _image_urls(self, messages: list, depth: int = 0, found=None) -> list[str]:
        """收集转发内容里所有图片地址，去重后供一次批量转述。"""
        found = [] if found is None else found
        for item in messages:
            for segment in _content(item):
                if _segment_type(segment) == "image":
                    url = _image_source(segment)
                    if url and url not in found:
                        found.append(url)
            nested = self._nested(item, depth)
            if nested and depth + 1 < self.max_depth:
                self._image_urls(nested, depth + 1, found)
        return found

    async def _captions(self, messages: list) -> dict:
        if self.captioner is None:
            return {}
        try:
            urls = self._image_urls(messages)
            if not urls:
                return {}
            result = self.captioner(urls)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    def _nested(self, item, depth: int) -> list:
        if depth + 1 >= self.max_depth or not isinstance(item, dict):
            return []
        nested: list = []
        for segment in _content(item):
            segment = _as_dict(segment)
            kind = _segment_type(segment)
            data = _as_dict(segment.get("data"))
            for source in (segment, data):
                for name in ("nodes", "messages"):
                    items = source.get(name)
                    if isinstance(items, list):
                        nested.extend(items)
                        break
                else:
                    continue
                break
            if kind in ("node", "nodes"):
                if isinstance(data.get("content"), list):
                    nested.append({**data, "type": "node"})
                elif isinstance(segment.get("content"), list):
                    nested.append(segment)
        return nested

    def _count(self, item, depth: int) -> int:
        total = 1
        for child in self._nested(item, depth):
            total += self._count(child, depth + 1)
        return total

    def _lines(self, messages: list, depth: int, budget: list, captions=None) -> list[str]:
        lines: list[str] = []
        pad = "  " * depth
        for item in messages:
            if budget[0] <= 0:
                budget[1] += self._count(item, depth)
                continue
            budget[0] -= 1
            lines.append(pad + self._line(item, captions))
            nested = self._nested(item, depth)
            if nested:
                lines.extend(self._lines(nested, depth + 1, budget, captions))
        return lines

    async def render(self, forward_id: str) -> str:
        try:
            payload = await asyncio.wait_for(self.fetcher(forward_id), self.timeout)
        except Exception as exc:
            self._log_failure(forward_id, exc)
            return "[合并转发: 获取失败]"
        messages = _messages_from_payload(payload)
        if not messages:
            self._log_failure(forward_id, "empty payload")
            return "[合并转发: 无内容]"
        captions = await self._captions(messages)
        budget = [self.max_nodes, 0]
        text = "\n".join(self._lines(messages, 0, budget, captions))
        if budget[1] > 0:
            text += f"\n(还有 {budget[1]} 条未显示)"
        return text[: self.max_chars]

    @staticmethod
    def _log_failure(forward_id, error) -> None:
        try:
            from astrbot.api.all import logger

            logger.warning(f"[dialoguesoul] 合并转发获取失败 {forward_id}: {error}")
        except Exception:
            pass
