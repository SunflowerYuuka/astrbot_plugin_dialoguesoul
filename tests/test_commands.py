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


class Gate:
    def __init__(self):
        self.muted_keys = {}

    def mute(self, key, until):
        self.muted_keys[tuple(key)] = until

    def unmute(self, key):
        self.muted_keys.pop(tuple(key), None)

    def muted(self, key, now):
        until = self.muted_keys.get(tuple(key))
        return until is not None and until > now


class Wake:
    def __init__(self):
        self.cleared = []

    def clear_chat(self, key):
        self.cleared.append(tuple(key))
        return True

    def is_active(self, key):
        return False


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

    async def test_mute_is_kept_in_memory_and_cancels_pending(self):
        gate = Gate()
        cancelled = []
        commands = Commands(Repo(), Config(), gate=gate, cancel=cancelled.append)
        event = Event()

        with mock.patch("dialoguesoul.commands.time.time", return_value=1000.0):
            result = await commands.mute(event, 5)

        key = ChatKey.from_event(event).as_tuple()
        self.assertEqual(result, "已静音 5 分钟")
        self.assertEqual(gate.muted_keys[key], 1300.0)
        self.assertEqual(cancelled, [key])

    async def test_mute_rejects_invalid_minutes(self):
        gate = Gate()
        commands = Commands(Repo(), Config(), gate=gate)

        with mock.patch("dialoguesoul.commands.time.time", return_value=1000.0):
            self.assertEqual(await commands.mute(Event(), -1), "已静音 1 分钟")
            self.assertEqual(await commands.mute(Event(), "bad"), "已静音 5 分钟")

        key = ChatKey.from_event(Event()).as_tuple()
        self.assertEqual(gate.muted_keys[key], 1300.0)

    async def test_unmute_only_clears_current_chat(self):
        gate = Gate()
        commands = Commands(Repo(), Config(), gate=gate)
        current = ChatKey.from_event(Event()).as_tuple()
        other = ChatKey.from_event(Event("2")).as_tuple()
        gate.mute(current, 9999.0)
        gate.mute(other, 9999.0)

        await commands.unmute(Event())

        self.assertNotIn(current, gate.muted_keys)
        self.assertIn(other, gate.muted_keys)

    async def test_reset_clears_wake_session_and_pending(self):
        wake = Wake()
        cancelled = []
        commands = Commands(
            Repo(), Config(), wake=wake, cancel=cancelled.append
        )

        await commands.reset(Event())

        key = ChatKey.from_event(Event()).as_tuple()
        self.assertEqual(wake.cleared, [key])
        self.assertEqual(cancelled, [key])

    async def test_status_reports_real_state(self):
        gate = Gate()
        config = Config(
            {"enabled": True, "trigger": {"strategy": "rules"}, "wake": {"enabled": True}}
        )
        commands = Commands(Repo(), config, gate=gate, wake=Wake())

        result = await commands.status(Event())

        self.assertIn("已启用", result)
        self.assertIn("rules", result)
        self.assertIn("唤醒会话：开启", result)
        self.assertIn("正常", result)

    async def test_status_and_help(self):
        commands = Commands(Repo(), Config())
        self.assertIn("DialoguesSoul", await commands.status(Event()))
        self.assertIn("/ds", await commands.help(Event()))


if __name__ == "__main__":
    unittest.main()
