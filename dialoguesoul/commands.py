from __future__ import annotations

import time

from . import config as cfg
from .models import ChatKey


class Commands:
    def __init__(self, repo, config):
        self.repo = repo
        self.config = config

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
        if group_id:
            await self.repo.clear(key.platform, key.self_id, "group", str(group_id))
        else:
            await self.repo.clear(*key.as_tuple())
        return "已重置聊天记录"

    async def mute(self, event, minutes: int = 5):
        key = ChatKey.from_event(event)
        mutes = self.config.get("_temp_mute")
        if not isinstance(mutes, dict):
            mutes = {}
            self.config["_temp_mute"] = mutes
        mutes[cfg.chat_key_id(key)] = {"until": time.time() + minutes * 60}
        save = getattr(self.config, "save_config", None)
        if callable(save):
            save()
        return f"已静音 {minutes} 分钟"

    async def unmute(self, event):
        key = ChatKey.from_event(event)
        mutes = self.config.get("_temp_mute")
        if isinstance(mutes, dict):
            mutes.pop(cfg.chat_key_id(key), None)
        save = getattr(self.config, "save_config", None)
        if callable(save):
            save()
        return "已恢复回复"

    async def status(self, event):
        return "DialoguesSoul 已运行"
