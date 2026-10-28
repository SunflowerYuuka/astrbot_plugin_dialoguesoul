import asyncio
import tempfile
import unittest
from pathlib import Path

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.context.components import (
    collect_forward_ids,
    collect_image_urls,
    collect_text,
    component_to_dict,
)
from dialoguesoul.models import ChatKey, ChatMessage
from dialoguesoul.storage.db import Database
from dialoguesoul.storage.history import HistoryRepository, SqliteHistoryRepository


class StorageTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.db"))
        await self.db.initialize()
        self.repo = SqliteHistoryRepository(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    def _msg(self, text, ts):
        return ChatMessage(
            platform="p", self_id="bot", chat_type="group", chat_id="1",
            message_id=f"m{ts}", sender_id="u", sender_name="U",
            timestamp=ts, components=[{"type": "plain", "text": text}],
        )

    async def test_append_and_recent(self):
        await self.repo.append(self._msg("a", 1.0))
        await self.repo.append(self._msg("b", 2.0))
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["a", "b"])

    async def test_recent_keeps_the_newest_and_returns_them_oldest_first(self):
        for i in range(5):
            await self.repo.append(self._msg(str(i), float(i)))
        rows = await self.repo.recent("p", "bot", "group", "1", 2)
        self.assertEqual([r.components[0]["text"] for r in rows], ["3", "4"])

    async def test_recent_zero_limit_returns_empty(self):
        await self.repo.append(self._msg("a", 1.0))
        self.assertEqual(await self.repo.recent("p", "bot", "group", "1", 0), [])

    async def test_recent_preserves_insertion_order_for_equal_timestamps(self):
        for text in ("a", "b", "c"):
            await self.repo.append(self._msg(text, 1.0))
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["a", "b", "c"])

    async def test_recent_treats_none_limit_as_zero(self):
        await self.repo.append(self._msg("a", 1.0))
        self.assertEqual(await self.repo.recent("p", "bot", "group", "1", None), [])

    async def test_recent_is_scoped_to_one_chat(self):
        await self.repo.append(self._msg("a", 1.0))
        other = ChatMessage(
            platform="p", self_id="bot", chat_type="group", chat_id="2",
            message_id="m9", sender_id="u", sender_name="U",
            timestamp=2.0, components=[{"type": "plain", "text": "z"}],
        )
        await self.repo.append(other)
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["a"])

    async def test_round_trip_keeps_all_fields(self):
        await self.repo.append(self._msg("a", 1.5))
        row = (await self.repo.recent("p", "bot", "group", "1", 10))[0]
        self.assertEqual(
            (
                row.platform, row.self_id, row.chat_type, row.chat_id,
                row.message_id, row.sender_id, row.sender_name, row.timestamp,
                row.components,
            ),
            ("p", "bot", "group", "1", "m1.5", "u", "U", 1.5,
             [{"type": "plain", "text": "a"}]),
        )

    async def test_clear(self):
        await self.repo.append(self._msg("a", 1.0))
        self.assertEqual(await self.repo.clear("p", "bot", "group", "1"), 1)
        self.assertEqual(await self.repo.recent("p", "bot", "group", "1", 10), [])

    async def test_count(self):
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 0)
        await self.repo.append(self._msg("a", 1.0))
        await self.repo.append(self._msg("b", 2.0))
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 2)
        self.assertEqual(await self.repo.count("p", "bot", "group", "2"), 0)

    async def test_prune_keeps_latest(self):
        for i in range(5):
            await self.repo.append(self._msg(str(i), float(i)))
        await self.repo.prune("p", "bot", "group", "1", keep_last=2)
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["3", "4"])

    async def test_prune_with_non_positive_keep_last_deletes_nothing(self):
        for i in range(3):
            await self.repo.append(self._msg(str(i), float(i)))
        self.assertEqual(await self.repo.prune("p", "bot", "group", "1", keep_last=0), 0)
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 3)

    async def test_prune_before_cutoff(self):
        for i in range(4):
            await self.repo.append(self._msg(str(i), float(i)))
        self.assertEqual(await self.repo.prune_before(2.0), 2)
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["2", "3"])

    async def test_concurrent_appends_are_serialized(self):
        await asyncio.gather(
            *[self.repo.append(self._msg(str(i), float(i))) for i in range(20)]
        )
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 20)

    async def test_initialize_sets_wal_and_busy_timeout(self):
        journal = await self.db.fetchone("PRAGMA journal_mode")
        timeout = await self.db.fetchone("PRAGMA busy_timeout")
        self.assertEqual(str(journal["journal_mode"]).lower(), "wal")
        self.assertEqual(int(timeout["timeout"]), 5000)

    async def test_repository_satisfies_history_protocol(self):
        self.assertIsInstance(self.repo, HistoryRepository)

    async def test_close_is_idempotent(self):
        await self.db.close()
        await self.db.close()

    async def test_timestamp_index_exists_for_retention_cleanup(self):
        rows = await self.db.fetchall("PRAGMA index_list(messages)")
        names = {row["name"] for row in rows}
        self.assertIn("idx_messages_timestamp", names)

    async def test_closed_database_ignores_late_writes(self):
        await self.db.close()

        self.assertEqual(await self.repo.append(self._msg("late", 1.0)), None)
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 0)
        self.assertEqual(await self.repo.recent("p", "bot", "group", "1", 5), [])
        self.assertEqual(await self.repo.prune_before(10.0), 0)


class _Event:
    def __init__(self, private_chat, sender_id="u1", group_id="g1"):
        self._private = private_chat
        self._sender_id = sender_id
        self._group_id = group_id

    def is_private_chat(self):
        return self._private

    def get_sender_id(self):
        return self._sender_id

    def get_group_id(self):
        return self._group_id

    def get_platform_name(self):
        return "aiocqhttp"

    def get_self_id(self):
        return "bot"


class ChatKeyTest(unittest.TestCase):
    def test_from_group_event_uses_group_id(self):
        key = ChatKey.from_event(_Event(private_chat=False, sender_id="u1", group_id=1234))
        self.assertEqual(key.as_tuple(), ("aiocqhttp", "bot", "group", "1234"))

    def test_from_private_event_uses_sender_id(self):
        key = ChatKey.from_event(_Event(private_chat=True, sender_id=5678, group_id=None))
        self.assertEqual(key.as_tuple(), ("aiocqhttp", "bot", "private", "5678"))

    def test_from_event_tolerates_missing_chat_id(self):
        key = ChatKey.from_event(_Event(private_chat=False, group_id=None))
        self.assertEqual(key.as_tuple(), ("aiocqhttp", "bot", "group", ""))


class _PlainComponent:
    type = "plain"

    def __init__(self, text):
        self.text = text


class _ImageComponent:
    type = "image"

    def __init__(self, url=None, file=None, path=None):
        self.url = url
        self.file = file
        self.path = path


class _AtComponent:
    type = "at"

    def __init__(self, qq):
        self.qq = qq
        self.name = None


class _NodeComponent:
    type = "node"

    def __init__(self, chain=None):
        self.chain = chain or []


class _ForwardComponent:
    type = "forward"

    def __init__(self, forward_id, chain=None, nodes=None):
        self.id = forward_id
        self.chain = chain or []
        self.nodes = nodes or []


class ComponentsTest(unittest.TestCase):
    def test_component_to_dict_keeps_type_and_known_fields(self):
        self.assertEqual(
            component_to_dict(_ImageComponent(url="http://x/y.png", file="y.png")),
            {"type": "image", "url": "http://x/y.png", "file": "y.png"},
        )
        self.assertEqual(component_to_dict(_AtComponent(qq="42")), {"type": "at", "qq": "42"})

    def test_component_to_dict_recurses_into_chain(self):
        forward = _ForwardComponent("f1", [_PlainComponent("hi")])
        self.assertEqual(
            component_to_dict(forward),
            {"type": "forward", "id": "f1", "chain": [{"type": "plain", "text": "hi"}]},
        )

    def test_component_to_dict_falls_back_to_class_name(self):
        self.assertEqual(component_to_dict(object()), {"type": "object"})

    def test_component_to_dict_keeps_path(self):
        self.assertEqual(
            component_to_dict(_ImageComponent(path="/tmp/a.png")),
            {"type": "image", "path": "/tmp/a.png"},
        )

    def test_component_to_dict_recurses_into_nodes(self):
        forward = _ForwardComponent("f2", nodes=[_NodeComponent([_PlainComponent("hi")])])
        self.assertEqual(
            component_to_dict(forward),
            {
                "type": "forward", "id": "f2",
                "nodes": [{"type": "node", "chain": [{"type": "plain", "text": "hi"}]}],
            },
        )

    def test_component_to_dict_passes_dict_nodes_through(self):
        forward = _ForwardComponent("f3", nodes=[{"type": "plain", "text": "hi"}])
        self.assertEqual(
            component_to_dict(forward),
            {"type": "forward", "id": "f3", "nodes": [{"type": "plain", "text": "hi"}]},
        )

    def test_collect_text(self):
        components = [
            {"type": "plain", "text": "a"},
            {"type": "image", "url": "http://x"},
            {"type": "plain", "text": "b"},
        ]
        self.assertEqual(collect_text(components), "ab")

    def test_collect_image_urls(self):
        components = [
            {"type": "plain", "text": "a"},
            {"type": "image", "url": "http://x/1.png"},
            {"type": "image"},
            {"type": "image", "url": "http://x/2.png"},
        ]
        self.assertEqual(collect_image_urls(components), ["http://x/1.png", "http://x/2.png"])

    def test_collect_image_urls_falls_back_to_file_then_path(self):
        components = [
            {"type": "image", "file": "a.png"},
            {"type": "image", "path": "/tmp/b.png"},
            {"type": "image", "url": "http://x/1.png", "file": "c.png"},
        ]
        self.assertEqual(
            collect_image_urls(components), ["a.png", "/tmp/b.png", "http://x/1.png"]
        )

    def test_collect_image_urls_dedupes_keeping_first_occurrence_order(self):
        components = [
            {"type": "image", "url": "http://x/2.png"},
            {"type": "image", "url": "http://x/1.png"},
            {"type": "image", "url": "http://x/2.png"},
            {"type": "image", "file": "http://x/1.png"},
        ]
        self.assertEqual(collect_image_urls(components), ["http://x/2.png", "http://x/1.png"])

    def test_collect_forward_ids(self):
        components = [
            {"type": "forward", "id": "f1"},
            {"type": "plain", "text": "a"},
            {"type": "forward"},
        ]
        self.assertEqual(collect_forward_ids(components), ["f1"])
