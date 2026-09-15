import asyncio
from unittest.mock import AsyncMock, MagicMock

from gitsnapbot.telegram_api import TelegramClient, TelegramError


def _client() -> TelegramClient:
    return TelegramClient(MagicMock(), MagicMock())


def test_replace_pinned_message_clears_then_pins() -> None:
    telegram = _client()
    telegram._call = AsyncMock(return_value=True)

    asyncio.run(telegram.replace_pinned_message(42, 99))

    methods = [call.args[0] for call in telegram._call.await_args_list]
    assert methods == ["unpinAllChatMessages", "pinChatMessage"]
    assert telegram._call.await_args_list[0].args[1] == {"chat_id": 42}
    assert telegram._call.await_args_list[1].args[1]["message_id"] == 99


def test_clear_pinned_messages_unpins_one_by_one_when_unpin_all_fails() -> None:
    telegram = _client()
    remaining = {"n": 3}

    async def fake_call(method: str, payload=None):
        if method == "unpinAllChatMessages":
            raise TelegramError("not a group")
        if method == "unpinChatMessage":
            if remaining["n"] == 0:
                raise TelegramError("no pinned messages")
            remaining["n"] -= 1
            return True
        raise AssertionError(method)

    telegram._call = AsyncMock(side_effect=fake_call)
    asyncio.run(telegram.clear_pinned_messages(7))

    methods = [call.args[0] for call in telegram._call.await_args_list]
    assert methods[0] == "unpinAllChatMessages"
    assert methods[1:] == ["unpinChatMessage"] * 4


def test_fallback_message_embeds_image_preview() -> None:
    telegram = _client()
    telegram.config.telegram_message_limit = 4000
    telegram._call = AsyncMock(side_effect=[TelegramError("no rich"), {"message_id": 1}])

    asyncio.run(
        telegram.send_message(
            1,
            "<h1>Report</h1>",
            fallback="Report",
            image_url="https://github.com/octocat.png?size=460",
        )
    )

    payload = telegram._call.await_args_list[1].args[1]
    assert payload["disable_web_page_preview"] is False
    assert "octocat.png" in payload["text"]
    assert "&#8205;" in payload["text"]
