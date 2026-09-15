from types import SimpleNamespace

from gitsnapbot.features.chatlock import bound_chat_id, is_allowed, should_bind


def test_unbound_chat_allows_anyone() -> None:
    assert is_allowed(1, None) is True
    assert is_allowed("99", "") is True
    assert should_bind(1, None) is True


def test_bound_chat_rejects_others() -> None:
    assert is_allowed(74711198, "74711198") is True
    assert is_allowed("74711198", 74711198) is True
    assert is_allowed(1, "74711198") is False
    assert should_bind(1, "74711198") is False


def test_bound_chat_id_prefers_config() -> None:
    config = SimpleNamespace(telegram_chat_id="111")
    store = SimpleNamespace(chat_id=lambda: "222")
    assert bound_chat_id(config, store) == "111"
    config.telegram_chat_id = None
    assert bound_chat_id(config, store) == "222"
