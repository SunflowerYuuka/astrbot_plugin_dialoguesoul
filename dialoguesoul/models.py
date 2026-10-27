from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatKey:
    platform: str
    self_id: str
    chat_type: str
    chat_id: str

    @classmethod
    def from_event(cls, event) -> "ChatKey":
        chat_type = "private" if event.is_private_chat() else "group"
        chat_id = event.get_sender_id() if chat_type == "private" else event.get_group_id()
        return cls(
            platform=str(event.get_platform_name()),
            self_id=str(event.get_self_id()),
            chat_type=chat_type,
            chat_id=str(chat_id or ""),
        )

    def as_tuple(self):
        return (self.platform, self.self_id, self.chat_type, self.chat_id)


@dataclass(frozen=True)
class ChatMessage:
    platform: str
    self_id: str
    chat_type: str
    chat_id: str
    message_id: str
    sender_id: str
    sender_name: str
    timestamp: float
    components: list[dict]
