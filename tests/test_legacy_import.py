import tempfile
import unittest
import warnings
from pathlib import Path

import jsonpickle

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.models import ChatMessage
from dialoguesoul.storage.db import Database
from dialoguesoul.storage.history import SqliteHistoryRepository
from dialoguesoul.storage.legacy_import import import_legacy_history


class _Comp:
    def __init__(self, text):
        self.type = "plain"
        self.text = text


class _ImageComp:
    type = "image"

    def __init__(self, url):
        self.url = url


class _Sender:
    def __init__(self):
        self.user_id = "u1"
        self.nickname = "U"


class _Msg:
    def __init__(self, text, ts, self_id=None):
        if self_id is not None:
            self.self_id = self_id
        self.message_id = f"m{ts}"
        self.sender = _Sender()
        self.message = [_Comp(text)]
        self.timestamp = ts


class _BadMsg(_Msg):
    def __init__(self, ts="not-a-number"):
        super().__init__("bad", 0.0)
        self.timestamp = ts


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def info(self, message):
        pass


def _encode(messages):
    return jsonpickle.encode(messages, unpicklable=True, keys=True)


class LegacyImportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "db.sqlite"))
        await self.db.initialize()
        self.repo = SqliteHistoryRepository(self.db)
        self.base = Path(self.tmp.name) / "chat_history"
        self.history_dir = self.base / "p" / "group"
        self.history_dir.mkdir(parents=True)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def _import(self, logger=None):
        return await import_legacy_history(self.db, self.repo, str(self.base), logger)

    async def test_import_once(self):
        (self.history_dir / "1.json").write_text(
            _encode([_Msg("a", 1.0), _Msg("b", 2.0)]), encoding="utf-8"
        )
        count = await self._import()
        self.assertEqual(count, 2)
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["a", "b"])

        again = await self._import()
        self.assertEqual(again, 0)
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 2)

    async def test_import_keeps_message_fields(self):
        (self.history_dir / "1.json").write_text(_encode([_Msg("a", 1.5)]), encoding="utf-8")
        await self._import()
        row = (await self.repo.recent("p", "bot", "group", "1", 10))[0]
        self.assertEqual(
            (
                row.platform, row.self_id, row.chat_type, row.chat_id,
                row.message_id, row.sender_id, row.sender_name, row.timestamp,
                row.components,
            ),
            ("p", "bot", "group", "1", "m1.5", "u1", "U", 1.5, [{"type": "plain", "text": "a"}]),
        )

    async def test_import_prefers_legacy_self_id(self):
        (self.history_dir / "1.json").write_text(
            _encode([_Msg("a", 1.0, self_id=12345)]), encoding="utf-8"
        )
        self.assertEqual(await self._import(), 1)
        self.assertEqual(await self.repo.count("p", "12345", "group", "1"), 1)

    async def test_import_keeps_rich_components(self):
        msg = _Msg("a", 1.0)
        msg.message = [_Comp("hi"), _ImageComp("http://x/1.png")]
        (self.history_dir / "1.json").write_text(_encode([msg]), encoding="utf-8")
        await self._import()
        row = (await self.repo.recent("p", "bot", "group", "1", 10))[0]
        self.assertEqual(
            row.components,
            [{"type": "plain", "text": "hi"}, {"type": "image", "url": "http://x/1.png"}],
        )

    async def test_import_handles_private_chat_directory(self):
        private_dir = self.base / "p" / "private"
        private_dir.mkdir(parents=True)
        (private_dir / "u9.json").write_text(_encode([_Msg("a", 1.0)]), encoding="utf-8")
        self.assertEqual(await self._import(), 1)
        self.assertEqual(await self.repo.count("p", "bot", "private", "u9"), 1)

    async def test_import_skips_unknown_chat_type_directory(self):
        weird_dir = self.base / "p" / "channel"
        weird_dir.mkdir(parents=True)
        (weird_dir / "c1.json").write_text(_encode([_Msg("a", 1.0)]), encoding="utf-8")
        self.assertEqual(await self._import(), 0)

    async def test_broken_file_is_skipped_and_others_imported(self):
        (self.history_dir / "1.json").write_text("{not json", encoding="utf-8")
        (self.history_dir / "2.json").write_text(_encode([_Msg("b", 2.0)]), encoding="utf-8")
        logger = _Logger()
        with warnings.catch_warnings():
            # jsonpickle 解码失败时会尝试 yaml 后端，插件侧无法避免其弃用告警。
            warnings.simplefilter("ignore", DeprecationWarning)
            count = await self._import(logger)
        self.assertEqual(count, 1)
        self.assertEqual(await self.repo.count("p", "bot", "group", "2"), 1)
        self.assertEqual(len(logger.warnings), 1)

    async def test_bad_message_is_skipped_and_rest_imported(self):
        (self.history_dir / "1.json").write_text(
            _encode([_Msg("a", 1.0), _BadMsg(), _Msg("b", 2.0)]), encoding="utf-8"
        )
        logger = _Logger()
        self.assertEqual(await self._import(logger), 2)
        rows = await self.repo.recent("p", "bot", "group", "1", 10)
        self.assertEqual([r.components[0]["text"] for r in rows], ["a", "b"])
        self.assertEqual(len(logger.warnings), 1)

    async def test_missing_base_path_marks_imported(self):
        missing = Path(self.tmp.name) / "no_such_history"
        self.assertEqual(
            await import_legacy_history(self.db, self.repo, str(missing)), 0
        )
        (self.history_dir / "1.json").write_text(_encode([_Msg("a", 1.0)]), encoding="utf-8")
        self.assertEqual(await self._import(), 0)
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 0)

    async def test_existing_database_is_not_imported_into(self):
        await self.repo.append(
            ChatMessage(
                platform="p", self_id="bot", chat_type="group", chat_id="1",
                message_id="m1", sender_id="u", sender_name="U",
                timestamp=1.0, components=[{"type": "plain", "text": "live"}],
            )
        )
        (self.history_dir / "1.json").write_text(_encode([_Msg("a", 1.0)]), encoding="utf-8")
        self.assertEqual(await self._import(), 0)
        self.assertEqual(await self.repo.count("p", "bot", "group", "1"), 1)

    async def test_import_is_marked_in_meta(self):
        (self.history_dir / "1.json").write_text(_encode([_Msg("a", 1.0)]), encoding="utf-8")
        await self._import()
        row = await self.db.fetchone("SELECT value FROM meta WHERE key='legacy_imported'")
        self.assertEqual(row["value"], "1")
