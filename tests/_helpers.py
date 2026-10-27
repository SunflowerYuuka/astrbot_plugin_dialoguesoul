import sys
import types


class _Plain:
    def __init__(self, text=""):
        self.text = text


class _At:
    def __init__(self, qq=""):
        self.qq = qq


class _Reply:
    def __init__(self, id="", sender_id=""):
        self.id = id
        self.sender_id = sender_id


class _MessageChain:
    def __init__(self, chain=None):
        self.chain = list(chain or [])


class _ProviderRequest:
    def __init__(self, **kwargs):
        self.prompt = kwargs.get("prompt", "")
        self.system_prompt = kwargs.get("system_prompt", "")
        self.contexts = kwargs.get("contexts", [])
        self.image_urls = kwargs.get("image_urls", [])
        self.func_tool = kwargs.get("func_tool")
        self.session_id = kwargs.get("session_id", "")
        self.conversation = None


def install_astrbot_stub():
    astrbot = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
    astrbot.__path__ = []
    api = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
    api.__path__ = []
    all_mod = sys.modules.setdefault("astrbot.api.all", types.ModuleType("astrbot.api.all"))
    all_mod.Plain = _Plain
    all_mod.At = _At
    all_mod.Reply = _Reply
    all_mod.MessageChain = _MessageChain
    all_mod.Star = type("Star", (), {})
    all_mod.Context = object
    all_mod.AstrBotConfig = dict
    all_mod.AstrMessageEvent = object
    all_mod.logger = types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )

    event_mod = sys.modules.setdefault("astrbot.api.event", types.ModuleType("astrbot.api.event"))
    event_mod.__path__ = []
    filter_mod = sys.modules.setdefault("astrbot.api.event.filter", types.ModuleType("astrbot.api.event.filter"))
    def decorator(*args, **kwargs):
        def wrap(func):
            return func
        return wrap
    for name in (
        "event_message_type", "on_llm_response", "on_decorating_result",
        "after_message_sent", "command_group", "command", "permission_type",
        "custom_filter",
    ):
        setattr(filter_mod, name, decorator)
    filter_mod.PermissionType = types.SimpleNamespace(ADMIN="admin")

    provider_mod = sys.modules.setdefault("astrbot.api.provider", types.ModuleType("astrbot.api.provider"))
    provider_mod.LLMResponse = type("LLMResponse", (), {})
    provider_mod.ProviderRequest = _ProviderRequest

    core = sys.modules.setdefault("astrbot.core", types.ModuleType("astrbot.core"))
    core.__path__ = []
    provider_pkg = sys.modules.setdefault("astrbot.core.provider", types.ModuleType("astrbot.core.provider"))
    provider_pkg.__path__ = []
    entities = sys.modules.setdefault(
        "astrbot.core.provider.entities", types.ModuleType("astrbot.core.provider.entities")
    )
    entities.ProviderRequest = _ProviderRequest
    components = sys.modules.setdefault(
        "astrbot.core.message.components", types.ModuleType("astrbot.core.message.components")
    )
    components.Plain = _Plain
    components.At = _At
    components.Reply = _Reply
