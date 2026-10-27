import types
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.context.components import (
    collect_forward_ids, collect_image_urls, collect_text, component_to_dict,
)
from dialoguesoul.context.persona import resolve_persona_prompt
from dialoguesoul.context.prompt import build_environment, build_system_prompt, format_history
from dialoguesoul.models import ChatMessage


def _message(index, components):
    return ChatMessage(
        "p", "bot", "group", "1", f"m{index}", "u", "U", float(index), components
    )


class ContextTest(unittest.TestCase):
    def test_component_dict_and_collectors(self):
        plain = types.SimpleNamespace(type="plain", text="hello")
        image = types.SimpleNamespace(type="image", url="http://img")
        forward = types.SimpleNamespace(type="forward", id="f1")
        self.assertEqual(component_to_dict(plain)["text"], "hello")
        self.assertEqual(collect_text([plain, image]), "hello")
        self.assertEqual(collect_image_urls([image]), ["http://img"])
        self.assertEqual(collect_forward_ids([forward]), ["f1"])

    def test_format_history_numbers_messages(self):
        msgs = [
            ChatMessage("p", "bot", "group", "1", "m1", "u", "U", 1.0, [{"type": "plain", "text": "a"}]),
            ChatMessage("p", "bot", "group", "1", "m2", "u", "U", 2.0, [{"type": "plain", "text": "b"}]),
        ]
        text = format_history(msgs)
        self.assertIn("1.", text)
        self.assertIn("a", text)
        self.assertIn("2.", text)

    def test_format_history_marks_non_text(self):
        text = format_history([_message(1, [{"type": "image", "url": "http://img"}])])
        self.assertIn("[非文本消息]", text)

    def test_system_prompt_contains_decision(self):
        text = build_system_prompt("persona", "env", "history", "extra", decision=True)
        self.assertIn("决策协议", text)
        self.assertIn("extra", text)

    def test_system_prompt_without_decision_omits_protocol(self):
        text = build_system_prompt("persona", "env", "", "", decision=False)
        self.assertNotIn("决策协议", text)
        self.assertIn("persona", text)

    def test_environment(self):
        event = types.SimpleNamespace(
            get_self_id=lambda: "bot",
            get_platform_name=lambda: "p",
            is_private_chat=lambda: False,
            get_group_id=lambda: "1",
            get_sender_name=lambda: "U",
            get_sender_id=lambda: "u",
        )
        self.assertIn("bot", build_environment(event))


class PersonaTest(unittest.IsolatedAsyncioTestCase):
    def _event(self):
        return types.SimpleNamespace(unified_msg_origin="p:bot:group:1")

    async def test_disabled_returns_empty(self):
        context = types.SimpleNamespace(persona_manager=None)
        config = {"persona": {"enabled": False}}
        self.assertEqual(await resolve_persona_prompt(context, self._event(), config), "")

    async def test_missing_manager_returns_empty(self):
        context = types.SimpleNamespace()
        self.assertEqual(await resolve_persona_prompt(context, self._event(), {}), "")

    async def test_returns_default_persona_prompt(self):
        class Manager:
            async def get_default_persona_v3(self, umo=""):
                self.umo = umo
                return {"prompt": "人格内容"}

        manager = Manager()
        context = types.SimpleNamespace(persona_manager=manager)
        self.assertEqual(await resolve_persona_prompt(context, self._event(), {}), "人格内容")
        self.assertEqual(manager.umo, "p:bot:group:1")

    async def test_manager_errors_return_empty(self):
        class Manager:
            async def get_default_persona_v3(self, umo=""):
                raise RuntimeError("boom")

        context = types.SimpleNamespace(persona_manager=Manager())
        self.assertEqual(await resolve_persona_prompt(context, self._event(), {}), "")

    async def test_empty_persona_returns_empty(self):
        class Manager:
            async def get_default_persona_v3(self, umo=""):
                return None

        context = types.SimpleNamespace(persona_manager=Manager())
        self.assertEqual(await resolve_persona_prompt(context, self._event(), {}), "")

    async def test_malformed_persona_config_falls_back_to_default(self):
        class Manager:
            async def get_default_persona_v3(self, umo=""):
                return {"prompt": "人格内容"}

        context = types.SimpleNamespace(persona_manager=Manager())
        self.assertEqual(
            await resolve_persona_prompt(context, self._event(), {"persona": None}),
            "人格内容",
        )


if __name__ == "__main__":
    unittest.main()
