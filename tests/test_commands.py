import unittest
from unittest import mock

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul import config as cfg
from dialoguesoul.commands import Commands
from dialoguesoul.models import ChatKey, ChatMessage


class Event:
    def __init__(self, group="1"):
        self.group = group

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"

    def get_group_id(self):
        return self.group

    def get_sender_id(self):
        return "u"

    def is_private_chat(self):
        return False


class Repo:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.recent_calls = []
        self.clear_calls = []

    async def recent(self, *args):
        self.recent_calls.append(args)
        return list(self.rows)

    async def clear(self, *args):
        self.clear_calls.append(args)
        return 1


class Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def save_config(self):
        self.saved += 1


def _message(text="hi"):
    return ChatMessage("p", "bot", "group", "1", "m1", "u", "U", 1.0, [{"type": "plain", "text": text}])


class CommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_history_formats_rows_and_caps_count(self):
        repo = Repo([_message("hi"), _message("there")])
        commands = Commands(repo, Config())

        result = await commands.history(Event(), 99)

        self.assertEqual(result, "U: hi\nU: there")
        self.assertEqual(repo.recent_calls, [("p", "bot", "group", "1", 20)])

    async def test_history_without_rows(self):
        commands = Commands(Repo(), Config())
        self.assertEqual(await commands.history(Event()), "暂无聊天记录")

    async def test_reset_current_and_named_group(self):
        repo = Repo()
        commands = Commands(repo, Config())

        await commands.reset(Event())
        await commands.reset(Event(), "99")

        self.assertEqual(
            repo.clear_calls,
            [("p", "bot", "group", "1"), ("p", "bot", "group", "99")],
        )

    async def test_mute_is_per_chat_and_saves_config(self):
        config = Config()
        commands = Commands(Repo(), config)
        event = Event()

        with mock.patch("dialoguesoul.commands.time.time", return_value=1000.0):
            result = await commands.mute(event, 5)

        key = cfg.chat_key_id(ChatKey.from_event(event))
        self.assertEqual(result, "已静音 5 分钟")
        self.assertEqual(config["_temp_mute"][key], {"until": 1300.0})
        self.assertEqual(config.saved, 1)

    async def test_unmute_only_clears_current_chat(self):
        config = Config()
        commands = Commands(Repo(), config)
        current = cfg.chat_key_id(ChatKey.from_event(Event()))
        other = cfg.chat_key_id(ChatKey.from_event(Event("2")))
        config["_temp_mute"] = {
            current: {"until": 9999.0},
            other: {"until": 9999.0},
            "until": 9999.0,
        }

        await commands.unmute(Event())

        self.assertNotIn(current, config["_temp_mute"])
        self.assertIn(other, config["_temp_mute"])
        self.assertEqual(config["_temp_mute"]["until"], 9999.0)
        self.assertEqual(config.saved, 1)

    async def test_status_and_help(self):
        commands = Commands(Repo(), Config())
        self.assertEqual(await commands.status(Event()), "DialoguesSoul 已运行")
        self.assertIn("/ds", await commands.help(Event()))


if __name__ == "__main__":
    unittest.main()
