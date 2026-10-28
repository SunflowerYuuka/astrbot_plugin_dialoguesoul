import types
import unittest

from tests._helpers import (
    RequestLLMMixin,
    _Forward,
    _Image,
    _Plain,
    install_astrbot_stub,
)

install_astrbot_stub()

from dialoguesoul.context.summary import SummaryService
from dialoguesoul.models import ChatMessage
from dialoguesoul.request_builder import RequestBuilder
from dialoguesoul.wake import WakeLimits, WakeSession


def _message(index, message_id=None, sender_id="u"):
    return ChatMessage(
        platform="p",
        self_id="bot",
        chat_type="group",
        chat_id="1",
        message_id=message_id if message_id is not None else f"m{index}",
        sender_id=sender_id,
        sender_name="U",
        timestamp=float(index),
        components=[{"type": "plain", "text": f"old{index}"}],
    )


class FakeEvent(RequestLLMMixin):
    def __init__(self, components=None):
        self.unified_msg_origin = "p:group:1"
        self.message_obj = types.SimpleNamespace(
            message=list(components)
            if components is not None
            else [_Plain(text="hello")],
            message_id="current",
        )
        self._extra = {}
        self.request = None
        self.call_llm = False

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"

    def get_group_id(self):
        return "1"

    def get_sender_id(self):
        return "u"

    def get_sender_name(self):
        return "U"

    def is_private_chat(self):
        return False

    def get_message_outline(self):
        return "hello"

    def set_extra(self, key, value):
        self._extra[key] = value

    def get_extra(self, key, default=None):
        return self._extra.get(key, default)


class FakeRepo:
    def __init__(self, messages=None):
        self.messages = list(messages) if messages is not None else [_message(0)]
        self.calls = []

    async def recent(self, *args):
        self.calls.append(args)
        return list(self.messages)


class FakeCaption:
    def __init__(self, captions=None):
        self.captions = dict(captions or {"http://img": "一只猫"})
        self.calls = []

    async def caption(self, urls, umo=""):
        self.calls.append((list(urls), umo))
        return dict(self.captions)


class FakeForward:
    def __init__(self, text="A: 转发内容"):
        self.text = text
        self.calls = []

    async def render(self, forward_id):
        self.calls.append(forward_id)
        return self.text


class FakeSummary:
    def __init__(self, text="压缩摘要"):
        self.text = text
        self.calls = []

    async def summarize(self, messages, umo, fallback=""):
        self.calls.append((list(messages), umo, fallback))
        return self.text


def _base_config():
    return {
        "context": {
            "history_limit": 10,
            "image_caption": {"enabled": False},
            "forward": {"parse": False},
            "summary": {"enabled": False},
        },
        "decision": {"max_context_messages": 20},
        "extra_prompt": {"enabled": False, "text": ""},
    }


async def fake_persona(context, event, config):
    return "persona"


def _builder(repo=None, **overrides):
    options = {
        "repo": repo if repo is not None else FakeRepo(),
        "persona_resolver": fake_persona,
        "caption_service": None,
        "forward_renderer": None,
    }
    options.update(overrides)
    return RequestBuilder(**options)


class RequestBuilderTest(unittest.IsolatedAsyncioTestCase):
    async def _build(self, builder, event, config, **kwargs):
        options = {
            "decision": True,
            "wake_session": None,
            "context": object(),
        }
        options.update(kwargs)
        return await builder.build(event, config, **options)

    async def test_marker_decision_request(self):
        event = FakeEvent()
        built = await self._build(_builder(), event, _base_config())

        self.assertTrue(built.request.prompt.startswith("hello"))
        self.assertIn("[参与判断]", built.request.system_prompt)
        self.assertNotIn("决策协议", built.request.system_prompt)
        self.assertIn("persona", built.request.system_prompt)
        self.assertEqual(built.request.contexts, [])
        self.assertEqual(built.request.session_id, "p:group:1")
        self.assertIsNone(built.request.func_tool)
        self.assertIsNone(built.request.tool_set)
        self.assertIn("tool_set", event.request_llm_kwargs)
        self.assertNotIn("func_tool", event.request_llm_kwargs)
        self.assertEqual(event.get_extra("ds_request_kind"), "decision")
        self.assertEqual(event.get_extra("ds_decision_format"), "marker")
        self.assertIs(event.get_extra("enable_streaming"), False)
        self.assertTrue(event.call_llm)
        self.assertIsNone(built.wake_meta)

    async def test_request_llm_rejects_removed_func_tool_argument(self):
        event = FakeEvent()
        with self.assertRaises(TypeError):
            event.request_llm(prompt="hello", func_tool=None)

    async def test_decision_uses_max_context_messages_and_normal_uses_history_limit(self):
        repo = FakeRepo([_message(i) for i in range(5)])
        config = _base_config()
        config["context"]["history_limit"] = 2
        config["decision"]["max_context_messages"] = 3

        await self._build(_builder(repo=repo), FakeEvent(), config, decision=True)
        await self._build(_builder(repo=repo), FakeEvent(), config, decision=False)

        self.assertEqual(
            repo.calls[-2:],
            [("p", "bot", "group", "1", 3), ("p", "bot", "group", "1", 2)],
        )

    async def test_current_message_is_excluded_from_history_context(self):
        repo = FakeRepo([_message(0, "m0", "u"), _message(1, "m1", "v")])
        event = FakeEvent()
        event.message_obj.message_id = "m1"

        built = await self._build(_builder(repo=repo), event, _base_config())

        self.assertIn("old0", built.request.system_prompt)
        self.assertNotIn("old1", built.request.system_prompt)
        self.assertEqual(
            event.get_extra("ds_history_map"),
            {1: {"id": "m0", "sender_id": "u"}},
        )

    async def test_proactive_reply_uses_reply_instruction(self):
        event = FakeEvent()
        built = await self._build(
            _builder(), event, _base_config(), proactive_reply=True
        )

        self.assertEqual(event.get_extra("ds_request_kind"), "proactive_reply")
        self.assertEqual(event.get_extra("ds_reply_format"), "plain")
        self.assertIn("[回复要求]", built.request.system_prompt)
        self.assertNotIn("[参与判断]", built.request.system_prompt)
        self.assertNotIn("[决策协议]", built.request.system_prompt)
        self.assertIs(event.get_extra("enable_streaming"), False)

    async def test_proactive_reply_json_keeps_multimessage_instruction(self):
        event = FakeEvent()
        built = await self._build(
            _builder(),
            event,
            _base_config(),
            decision_format="json",
            proactive_reply=True,
        )

        self.assertEqual(event.get_extra("ds_request_kind"), "proactive_reply")
        self.assertEqual(event.get_extra("ds_reply_format"), "json")
        self.assertIn("messages", built.request.system_prompt)
        self.assertIn("quote", built.request.system_prompt)
        self.assertNotIn("action", built.request.system_prompt)

    async def test_json_decision_request(self):
        event = FakeEvent()
        built = await self._build(
            _builder(), event, _base_config(), decision_format="json"
        )

        self.assertIn("决策协议", built.request.system_prompt)
        self.assertNotIn("[参与判断]", built.request.system_prompt)
        self.assertEqual(event.get_extra("ds_request_kind"), "decision")
        self.assertEqual(event.get_extra("ds_decision_format"), "json")

    async def test_normal_request_has_no_decision_instruction(self):
        event = FakeEvent()
        built = await self._build(
            _builder(), event, _base_config(), decision=False
        )

        self.assertTrue(built.request.prompt.startswith("hello"))
        self.assertNotIn("决策协议", built.request.system_prompt)
        self.assertNotIn("[参与判断]", built.request.system_prompt)
        self.assertEqual(event.get_extra("ds_request_kind"), "normal")
        self.assertIsNone(event.get_extra("ds_decision_format"))
        self.assertIsNone(event.get_extra("enable_streaming"))
        self.assertTrue(event.call_llm)

    async def test_history_is_loaded_and_mapped(self):
        repo = FakeRepo([_message(0, "m0", "u"), _message(1, "m2", "v")])
        config = _base_config()
        config["decision"]["max_context_messages"] = 2
        event = FakeEvent()

        built = await self._build(_builder(repo=repo), event, config)

        self.assertEqual(repo.calls, [("p", "bot", "group", "1", 2)])
        self.assertEqual(
            event.get_extra("ds_history_map"),
            {
                1: {"id": "m0", "sender_id": "u"},
                2: {"id": "m2", "sender_id": "v"},
            },
        )
        self.assertIn("old0", built.request.system_prompt)
        self.assertIn("old1", built.request.system_prompt)

    async def test_history_map_skips_messages_without_id(self):
        repo = FakeRepo([_message(0, ""), _message(1, "m2", "v")])
        event = FakeEvent()

        await self._build(_builder(repo=repo), event, _base_config())

        self.assertEqual(
            event.get_extra("ds_history_map"),
            {2: {"id": "m2", "sender_id": "v"}},
        )

    async def test_caption_is_added_for_decision_when_enabled(self):
        image = _Image(url="http://img")
        caption = FakeCaption({"http://img": "一只猫"})
        config = _base_config()
        config["context"]["image_caption"]["enabled"] = True
        event = FakeEvent([image])

        built = await self._build(
            _builder(caption_service=caption), event, config
        )

        self.assertEqual(caption.calls, [(["http://img"], "p:group:1")])
        self.assertIn("[图片转述]", built.request.prompt)
        self.assertIn("一只猫", built.request.prompt)
        self.assertEqual(built.request.image_urls, ["http://img"])

    async def test_extra_image_urls_are_merged_and_captioned(self):
        image = _Image(url="http://now")
        caption = FakeCaption({"http://now": "当前图", "http://wait": "等待图"})
        config = _base_config()
        config["context"]["image_caption"]["enabled"] = True
        event = FakeEvent([_Plain(text="看图"), image])

        built = await self._build(
            _builder(caption_service=caption),
            event,
            config,
            extra_image_urls=["http://wait", "http://now"],
        )

        self.assertEqual(built.request.image_urls, ["http://now", "http://wait"])
        self.assertEqual(
            caption.calls, [(["http://now", "http://wait"], "p:group:1")]
        )
        self.assertIn("当前图", built.request.prompt)
        self.assertIn("等待图", built.request.prompt)

    async def test_caption_is_optional(self):
        image = _Image(url="http://img")
        caption = FakeCaption()
        event = FakeEvent([image])

        built = await self._build(_builder(caption_service=caption), event, _base_config())
        self.assertEqual(caption.calls, [])
        self.assertEqual(built.request.prompt, "[非文本消息]")

        config = _base_config()
        config["context"]["image_caption"]["enabled"] = True
        other_event = FakeEvent([image])
        built = await self._build(
            _builder(caption_service=caption), other_event, config, decision=False
        )
        self.assertEqual(caption.calls, [])
        self.assertEqual(built.request.image_urls, ["http://img"])

        third_event = FakeEvent([image])
        built = await self._build(_builder(), third_event, config)
        self.assertEqual(built.request.prompt, "[非文本消息]")

    async def test_forward_is_rendered_when_enabled(self):
        forward = _Forward(id="f1")
        renderer = FakeForward()
        config = _base_config()
        config["context"]["forward"]["parse"] = True
        event = FakeEvent([_Plain(text="hi"), forward])

        built = await self._build(
            _builder(forward_renderer=renderer), event, config
        )

        self.assertEqual(renderer.calls, ["f1"])
        self.assertIn("[合并转发]", built.request.prompt)
        self.assertIn("A: 转发内容", built.request.prompt)

        other_renderer = FakeForward()
        other_event = FakeEvent([forward])
        built = await self._build(
            _builder(forward_renderer=other_renderer), other_event, _base_config()
        )
        self.assertEqual(other_renderer.calls, [])
        self.assertEqual(built.request.prompt, "[非文本消息]")

    async def test_summary_replaces_history_when_over_threshold(self):
        calls = []

        async def summarizer(umo, fallback):
            calls.append((umo, fallback))
            return "SUMMARIZED"

        service = SummaryService(summarizer, threshold=3)
        repo = FakeRepo([_message(i) for i in range(3)])
        config = _base_config()
        config["context"]["summary"]["enabled"] = True
        event = FakeEvent()

        built = await self._build(
            _builder(repo=repo),
            event,
            config,
            decision=False,
            summary_service=service,
        )

        self.assertEqual(calls[0][0], "p:group:1")
        self.assertIn("old0", calls[0][1])
        self.assertIn("SUMMARIZED", built.request.system_prompt)
        self.assertNotIn("old0", built.request.system_prompt)

    async def test_summary_below_threshold_uses_history(self):
        calls = []

        async def summarizer(umo, fallback):
            calls.append((umo, fallback))
            return "SUMMARIZED"

        service = SummaryService(summarizer, threshold=3)
        repo = FakeRepo([_message(i) for i in range(2)])
        config = _base_config()
        config["context"]["summary"]["enabled"] = True
        event = FakeEvent()

        built = await self._build(
            _builder(repo=repo),
            event,
            config,
            decision=False,
            summary_service=service,
        )

        self.assertEqual(calls, [])
        self.assertIn("old0", built.request.system_prompt)

    async def test_summary_is_optional_and_respects_enabled(self):
        service = FakeSummary()
        repo = FakeRepo([_message(0)])
        event = FakeEvent()

        built = await self._build(
            _builder(repo=repo),
            event,
            _base_config(),
            decision=False,
            summary_service=service,
        )
        self.assertEqual(service.calls, [])
        self.assertIn("old0", built.request.system_prompt)

        config = _base_config()
        config["context"]["summary"]["enabled"] = True
        other_event = FakeEvent()
        built = await self._build(
            _builder(repo=repo),
            other_event,
            config,
            decision=False,
            summary_service=None,
        )
        self.assertIn("old0", built.request.system_prompt)

    async def test_wake_metadata_marks_existing_session(self):
        limits = WakeLimits(duration_seconds=300, max_replies=5, idle_timeout_seconds=120)
        session = WakeSession(
            limits=limits,
            started_at=0.0,
            last_activity_at=0.0,
            session_id="s1",
        )
        event = FakeEvent()

        built = await self._build(
            _builder(), event, _base_config(), wake_session=session
        )

        self.assertEqual(
            built.wake_meta,
            {
                "session_id": "s1",
                "limits": limits,
                "starts_session": False,
            },
        )

    async def test_wake_final_prompt_is_injected_when_session_starts_and_cap_is_one(self):
        limits = WakeLimits(duration_seconds=300, max_replies=1, idle_timeout_seconds=120)
        config = _base_config()
        config["wake"] = {"final_reply_prompt": "请自然收尾"}

        built = await self._build(
            _builder(),
            FakeEvent(),
            config,
            wake_session=None,
            wake_starts=True,
            wake_limits=limits,
        )

        self.assertIn("[唤醒收尾提示]", built.request.system_prompt)

    async def test_wake_final_prompt_is_injected_on_last_reply(self):
        limits = WakeLimits(duration_seconds=300, max_replies=5, idle_timeout_seconds=120)
        session = WakeSession(
            limits=limits,
            started_at=0.0,
            last_activity_at=0.0,
            session_id="s1",
            consumed_replies=4,
        )
        config = _base_config()
        config["wake"] = {"final_reply_prompt": "请自然收尾"}

        built = await self._build(
            _builder(), FakeEvent(), config, wake_session=session
        )

        self.assertIn("[唤醒收尾提示]", built.request.system_prompt)
        self.assertIn("请自然收尾", built.request.system_prompt)

    async def test_wake_final_prompt_not_injected_before_last_reply(self):
        limits = WakeLimits(duration_seconds=300, max_replies=5, idle_timeout_seconds=120)
        session = WakeSession(
            limits=limits,
            started_at=0.0,
            last_activity_at=0.0,
            session_id="s1",
            consumed_replies=3,
        )
        config = _base_config()
        config["wake"] = {"final_reply_prompt": "请自然收尾"}

        built = await self._build(
            _builder(), FakeEvent(), config, wake_session=session
        )

        self.assertNotIn("[唤醒收尾提示]", built.request.system_prompt)

    async def test_wake_final_prompt_skipped_when_unlimited_or_empty(self):
        config = _base_config()
        config["wake"] = {"final_reply_prompt": "请自然收尾"}
        unlimited = WakeSession(
            limits=WakeLimits(300, 0, 120),
            started_at=0.0,
            last_activity_at=0.0,
            session_id="s1",
            consumed_replies=99,
        )
        built = await self._build(
            _builder(), FakeEvent(), config, wake_session=unlimited
        )
        self.assertNotIn("[唤醒收尾提示]", built.request.system_prompt)

        config["wake"] = {"final_reply_prompt": ""}
        last = WakeSession(
            limits=WakeLimits(300, 1, 120),
            started_at=0.0,
            last_activity_at=0.0,
            session_id="s1",
        )
        built = await self._build(_builder(), FakeEvent(), config, wake_session=last)
        self.assertNotIn("[唤醒收尾提示]", built.request.system_prompt)


if __name__ == "__main__":
    unittest.main()
