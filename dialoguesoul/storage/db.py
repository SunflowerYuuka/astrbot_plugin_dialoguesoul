import asyncio
import os
import sqlite3

from .schema import SCHEMA_STATEMENTS


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()

    async def initialize(self):
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self):
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        for statement in SCHEMA_STATEMENTS:
            self._conn.execute(statement)
        self._conn.commit()

    async def execute(self, sql, params=()):
        async with self._lock:
            return await asyncio.to_thread(self._execute_sync, sql, params)

    def _execute_sync(self, sql, params):
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    async def fetchall(self, sql, params=()):
        async with self._lock:
            return await asyncio.to_thread(
                lambda: [dict(row) for row in self._conn.execute(sql, params).fetchall()]
            )

    async def fetchone(self, sql, params=()):
        async with self._lock:
            return await asyncio.to_thread(
                lambda: (
                    dict(row) if (row := self._conn.execute(sql, params).fetchone()) else None
                )
            )

    async def close(self):
        async with self._lock:
            await asyncio.to_thread(self._conn.close)
