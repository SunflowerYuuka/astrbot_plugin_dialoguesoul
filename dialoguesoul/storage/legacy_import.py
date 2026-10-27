"""旧 SpectreCore 历史（JSON）到 SQLite 的一次性导入。

旧插件把消息按 ``<base>/<platform>/<group|private>/<chat_id>.json`` 组织，
文件内容是 ``jsonpickle`` 序列化的 AstrBotMessage 列表。本模块只负责读取
并转换为本插件自己的存储模型，不依赖旧插件的任何代码。
"""

from __future__ import annotations

from pathlib import Path

from ..context.components import component_to_dict
from ..models import ChatMessage

try:  # pragma: no cover - 依赖缺失时降级为不导入
    import jsonpickle
except Exception:  # pragma: no cover
    jsonpickle = None

_CHAT_TYPES = ("group", "private")
_MARKER_KEY = "legacy_imported"
# 标记值：完整导入成功 / 有失败 / 因库内已有数据而跳过
_MARKER_DONE = "1"
_MARKER_PARTIAL = "partial"
_MARKER_SKIPPED = "skipped_existing"
_DEFAULT_SELF_ID = "bot"


async def _mark_imported(db, status: str = _MARKER_DONE) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (_MARKER_KEY, status)
    )


async def _has_messages(db) -> bool:
    row = await db.fetchone("SELECT COUNT(*) AS c FROM messages")
    return bool(row) and int(row["c"] or 0) > 0


def _invalid_reason(item) -> str:
    """判断旧历史条目是否可用；可用返回空串，否则返回原因。

    jsonpickle 以 ``on_missing='ignore'`` 解码时，类无法解析的条目会退化成
    普通 dict，直接取值只会得到一条全空白的记录，因此这里显式拦截。
    """
    if isinstance(item, dict):
        return "条目是字典（旧类未能解析）"
    if item is None or isinstance(item, (str, bytes, int, float, bool)):
        return f"条目类型异常 {type(item).__name__}"
    components = getattr(item, "message", None)
    if not isinstance(components, (list, tuple)) or not components:
        return "条目缺少消息组件"
    sender = getattr(item, "sender", None)
    if sender is None or isinstance(sender, dict):
        return "条目缺少发送者信息"
    return ""


def _to_chat_message(item, platform, chat_type, chat_id) -> ChatMessage:
    sender = getattr(item, "sender", None)
    self_id = getattr(item, "self_id", None)
    return ChatMessage(
        platform=str(platform),
        self_id=str(self_id) if self_id else _DEFAULT_SELF_ID,
        chat_type=chat_type,
        chat_id=str(chat_id),
        message_id=str(getattr(item, "message_id", "") or ""),
        sender_id=str(getattr(sender, "user_id", "") or ""),
        sender_name=str(getattr(sender, "nickname", "") or ""),
        timestamp=float(getattr(item, "timestamp", 0) or 0),
        components=[
            component_to_dict(component)
            for component in (getattr(item, "message", None) or [])
        ],
    )


def _read_messages(file_path, logger):
    """读取并解码单个旧历史文件；无法读取或格式不对时返回 None。"""
    try:
        raw = file_path.read_text(encoding="utf-8")
        decoded = jsonpickle.decode(raw, keys=True)
    except Exception as exc:  # noqa: BLE001
        if logger:
            logger.warning(f"旧历史导入失败 {file_path}: {exc}")
        return None
    if not isinstance(decoded, (list, tuple)):
        if logger:
            logger.warning(f"旧历史格式无法识别，已跳过 {file_path}")
        return None
    return decoded


async def import_legacy_history(db, repo, base_path: str, logger=None) -> int:
    """把旧 JSON 历史导入 ``repo``，返回导入条数。

    只执行一次：``meta.legacy_imported`` 存在时直接返回 0。数据库已有消息
    时不覆盖，写 ``skipped_existing`` 标记后返回 0。文件解码失败、文件格式
    不对、单条消息不可用或入库失败都只记录并跳过，全部无失败时标记为
    ``1``，有任一失败时标记为 ``partial``（便于事后判断是否需要人工补导）。
    """
    if jsonpickle is None:
        return 0

    row = await db.fetchone("SELECT value FROM meta WHERE key=?", (_MARKER_KEY,))
    if row:
        return 0

    if await _has_messages(db):
        await _mark_imported(db, _MARKER_SKIPPED)
        if logger:
            logger.info("数据库已有消息，跳过旧历史导入（标记 skipped_existing）")
        return 0

    root = Path(base_path)
    if not root.exists():
        await _mark_imported(db, _MARKER_DONE)
        if logger:
            logger.info(f"旧历史目录不存在，无需导入: {root}")
        return 0

    total = 0
    failures = 0
    for file_path in sorted(root.glob("*/*/*.json")):
        chat_type = file_path.parent.name
        if chat_type not in _CHAT_TYPES:
            continue
        platform = file_path.parent.parent.name
        chat_id = file_path.stem
        messages = _read_messages(file_path, logger)
        if messages is None:
            failures += 1
            continue
        for item in messages:
            reason = _invalid_reason(item)
            if reason:
                failures += 1
                if logger:
                    logger.warning(f"旧历史条目已跳过（{reason}）{file_path}")
                continue
            try:
                await repo.append(_to_chat_message(item, platform, chat_type, chat_id))
                total += 1
            except Exception as exc:  # noqa: BLE001
                failures += 1
                if logger:
                    logger.warning(f"旧历史单条导入失败 {file_path}: {exc}")

    status = _MARKER_DONE if failures == 0 else _MARKER_PARTIAL
    await _mark_imported(db, status)
    if logger:
        logger.info(
            f"旧历史导入结束：共 {total} 条，失败 {failures} 处，标记 {status}"
        )
    return total
