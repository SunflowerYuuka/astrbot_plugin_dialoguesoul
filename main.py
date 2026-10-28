from astrbot.api.all import *
from astrbot.api.event import filter
from astrbot.api.provider import LLMResponse

from .dialoguesoul.commands import Commands
from .dialoguesoul.plugin import DialoguesSoulPlugin
from .dialoguesoul.storage.db import Database
from .dialoguesoul.storage.history import SqliteHistoryRepository
from .dialoguesoul.storage.legacy_import import import_legacy_history
from .dialoguesoul.storage.paths import resolve_db_path


@register(
    "dialoguesoul",
    "SunflowerYuuka",
    "DialoguesSoul",
    "1.2.0",
    "https://github.com/SunflowerYuuka/astrbot_plugin_dialoguesoul",
)
class DialoguesSoul(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        db_path = resolve_db_path(config)
        self.db = Database(db_path)
        self.repo = SqliteHistoryRepository(self.db)
        self.core = DialoguesSoulPlugin(context, config, self.repo)
        self.commands = Commands(self.repo, config)

    async def initialize(self):
        await self.db.initialize()
        await import_legacy_history(self.db, self.repo, "data/chat_history", logger)

    async def terminate(self):
        await self.core.close()
        await self.db.close()

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        async for result in self.core.handle_message(event):
            yield result

    @event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        async for result in self.core.handle_message(event):
            yield result

    @filter.on_llm_response(priority=10000)
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        self.core.hooks.on_llm_response(event, resp)

    @filter.on_decorating_result(priority=10000)
    async def on_decorating_result(self, event: AstrMessageEvent):
        await self.core.hooks.on_decorating_result(event)

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        await self.core.hooks.after_message_sent(event)

    @filter.command_group("ds")
    def ds(self):
        pass

    @ds.command("help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(await self.commands.help(event))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @ds.command("history")
    async def history(self, event: AstrMessageEvent, count: int = 10):
        yield event.plain_result(await self.commands.history(event, count))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @ds.command("reset")
    async def reset(self, event: AstrMessageEvent, group_id: str | None = None):
        yield event.plain_result(await self.commands.reset(event, group_id))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @ds.command("mute")
    async def mute(self, event: AstrMessageEvent, minutes: int = 5):
        yield event.plain_result(await self.commands.mute(event, minutes))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @ds.command("unmute")
    async def unmute(self, event: AstrMessageEvent):
        yield event.plain_result(await self.commands.unmute(event))

    @ds.command("status")
    async def status(self, event: AstrMessageEvent):
        yield event.plain_result(await self.commands.status(event))
