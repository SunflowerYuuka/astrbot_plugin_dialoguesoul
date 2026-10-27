from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from dialoguesoul.models import ChatMessage

from .db import Database


@runtime_checkable
class HistoryRepository(Protocol):
    async def append(self, message: ChatMessage) -> None: ...
    async def recent(self, platform, self_id, chat_type, chat_id, limit) -> list[ChatMessage]: ...
    async def clear(self, platform, self_id, chat_type, chat_id) -> int: ...
    async def count(self, platform, self_id, chat_type, chat_id) -> int: ...
    async def prune_before(self, cutoff: float) -> int: ...
    async def prune(self, platform, self_id, chat_type, chat_id, keep_last: int) -> int: ...


class SqliteHistoryRepository:
    def __init__(self, db: Database):
        self.db = db

    async def append(self, message: ChatMessage) -> None:
        await self.db.execute(
            """
            INSERT INTO messages
              (platform, self_id, chat_type, chat_id, message_id, sender_id, sender_name, timestamp, components)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.platform, message.self_id, message.chat_type, message.chat_id,
                message.message_id, message.sender_id, message.sender_name,
                message.timestamp, json.dumps(message.components, ensure_ascii=False),
            ),
        )

    async def recent(self, platform, self_id, chat_type, chat_id, limit) -> list[ChatMessage]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM messages
            WHERE platform=? AND self_id=? AND chat_type=? AND chat_id=?
            ORDER BY timestamp DESC, id DESC LIMIT ?
            """,
            (platform, self_id, chat_type, chat_id, max(0, int(limit or 0))),
        )
        rows.reverse()
        return [
            ChatMessage(
                platform=r["platform"], self_id=r["self_id"], chat_type=r["chat_type"],
                chat_id=r["chat_id"], message_id=r["message_id"] or "",
                sender_id=r["sender_id"] or "", sender_name=r["sender_name"] or "",
                timestamp=r["timestamp"],
                components=json.loads(r["components"] or "[]"),
            )
            for r in rows
        ]

    async def clear(self, platform, self_id, chat_type, chat_id) -> int:
        return await self.db.execute(
            "DELETE FROM messages WHERE platform=? AND self_id=? AND chat_type=? AND chat_id=?",
            (platform, self_id, chat_type, chat_id),
        )

    async def count(self, platform, self_id, chat_type, chat_id) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM messages WHERE platform=? AND self_id=? AND chat_type=? AND chat_id=?",
            (platform, self_id, chat_type, chat_id),
        )
        return int(row["c"]) if row else 0

    async def prune_before(self, cutoff: float) -> int:
        return await self.db.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))

    async def prune(self, platform, self_id, chat_type, chat_id, keep_last: int) -> int:
        if keep_last <= 0:
            return 0
        return await self.db.execute(
            """
            DELETE FROM messages
            WHERE platform=? AND self_id=? AND chat_type=? AND chat_id=?
              AND id NOT IN (
                SELECT id FROM messages
                WHERE platform=? AND self_id=? AND chat_type=? AND chat_id=?
                ORDER BY timestamp DESC, id DESC LIMIT ?
              )
            """,
            (
                platform, self_id, chat_type, chat_id,
                platform, self_id, chat_type, chat_id, keep_last,
            ),
        )
