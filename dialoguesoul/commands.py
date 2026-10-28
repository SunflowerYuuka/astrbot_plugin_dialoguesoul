from __future__ import annotations

import time

from . import config as cfg
from .models import ChatKey

_MAX_MUTE_MINUTES = 7 * 24 * 60


class Commands:
    def __init__(self, repo, config, gate=None, wake=None, cancel=None):
        self.repo = repo
        self.config = config
        self.gate = gate
        self.wake = wake
        self.cancel = cancel

    async def help(self, event):
        return "DialoguesSoul 指令：/ds help、history、reset、mute、unmute、status"

    async def history(self, event, count: int = 10):
        key = ChatKey.from_event(event)
        rows = await self.repo.recent(*key.as_tuple(), min(max(count, 1), 20))
        return "\n".join(
            f"{m.sender_name}: "
            + "".join(
                str(c.get("text", ""))
                for c in m.components
                if c.get("type") == "plain"
            )
            for m in rows
        ) or "暂无聊天记录"

    async def reset(self, event, group_id: str | None = None):
        key = ChatKey.from_event(event)
        target = (
            (key.platform, key.self_id, "group", str(group_id))
            if group_id
            else key.as_tuple()
        )
        await self.repo.clear(*target)
        self._cancel(target)
        return "已重置聊天记录"

    async def mute(self, event, minutes: int = 5):
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 5
        minutes = max(1, min(minutes, _MAX_MUTE_MINUTES))
        key = ChatKey.from_event(event)
        if self.gate is not None:
            self.gate.mute(key.as_tuple(), time.time() + minutes * 60)
        self._cancel(key.as_tuple())
        return f"已静音 {minutes} 分钟"

    async def unmute(self, event):
        key = ChatKey.from_event(event)
        if self.gate is not None:
            self.gate.unmute(key.as_tuple())
        return "已恢复回复"

    async def status(self, event):
        key = ChatKey.from_event(event)
        strategy = cfg.get(self.config, "trigger.strategy", "window")
        wake_on = bool(cfg.get(self.config, "wake.enabled", False))
        lines = [
            f"DialoguesSoul {'已启用' if cfg.get(self.config, 'enabled', False) else '未启用'}",
            f"触发策略：{strategy}",
            f"唤醒会话：{'开启' if wake_on else '关闭'}",
        ]
        if self.gate is not None:
            muted = self.gate.muted(key.as_tuple(), time.time())
            lines.append(f"当前聊天：{'静音中' if muted else '正常'}")
        if self.wake is not None:
            active = self.wake.is_active(key.as_tuple())
            lines.append(f"唤醒状态：{'进行中' if active else '未激活'}")
        return "\n".join(lines)

    def _cancel(self, key):
        if self.wake is not None:
            self.wake.clear_chat(key)
        if self.cancel is not None:
            self.cancel(key)
