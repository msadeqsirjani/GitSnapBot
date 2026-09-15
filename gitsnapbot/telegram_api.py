from __future__ import annotations

import logging
from typing import Any

import httpx

from gitsnapbot.config import Config
from gitsnapbot.logsetup import short_url
from gitsnapbot.messages import escape

log = logging.getLogger("gitsnapbot.telegram")


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, client: httpx.AsyncClient, config: Config) -> None:
        self.client = client
        self.config = config
        self.token = config.telegram_bot_token
        self.verbose_http = config.log_http

    def _url(self, method: str) -> str:
        return f"{self.config.telegram_api_url}/bot{self.token}/{method}"

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        response = await self.client.post(self._url(method), json=payload or {})
        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramError(f"Invalid Telegram response: {response.text[:300]}") from exc
        if not data.get("ok"):
            log.error("Telegram %s failed  %s", method, data.get("description"))
            raise TelegramError(data.get("description") or f"Telegram {method} failed")
        if method != "getUpdates" and self.verbose_http:
            log.info("Telegram %s  ok  %s", method, short_url(self._url(method)))
        elif method == "getUpdates":
            log.debug("Telegram getUpdates  %s updates", len(data.get("result") or []))
        return data.get("result")

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        await self._call("setMyCommands", {"commands": commands})

    async def set_chat_menu_button(self) -> None:
        await self._call("setChatMenuButton", {"menu_button": {"type": "commands"}})

    async def set_my_short_description(self, description: str) -> None:
        await self._call("setMyShortDescription", {"short_description": description})

    async def set_my_description(self, description: str) -> None:
        await self._call("setMyDescription", {"description": description})

    async def pin_chat_message(self, chat_id: str | int, message_id: int) -> None:
        await self._call(
            "pinChatMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": True,
            },
        )

    async def unpin_chat_message(
        self, chat_id: str | int, message_id: int | None = None
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id}
        if message_id is not None:
            payload["message_id"] = message_id
        await self._call("unpinChatMessage", payload)

    async def unpin_all_chat_messages(self, chat_id: str | int) -> None:
        await self._call("unpinAllChatMessages", {"chat_id": chat_id})

    async def clear_pinned_messages(self, chat_id: str | int) -> None:
        try:
            await self.unpin_all_chat_messages(chat_id)
            return
        except TelegramError as exc:
            log.info("unpinAllChatMessages unavailable (%s) — unpinning one by one", exc)
        for _ in range(100):
            try:
                await self.unpin_chat_message(chat_id)
            except TelegramError:
                break

    async def replace_pinned_message(self, chat_id: str | int, message_id: int) -> None:
        await self.clear_pinned_messages(chat_id)
        await self.pin_chat_message(chat_id, message_id)

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        fallback: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        rich: bool = True,
        image_url: str | None = None,
    ) -> Any:
        markup = reply_markup
        if rich:
            try:
                payload: dict[str, Any] = {
                    "chat_id": chat_id,
                    "rich_message": {"html": text},
                }
                if markup:
                    payload["reply_markup"] = markup
                return await self._call("sendRichMessage", payload)
            except TelegramError as exc:
                log.info("Rich messages unavailable (%s) — sending HTML fallback", exc)

        plain = fallback or text
        if image_url:
            plain = f'<a href="{escape(image_url)}">&#8205;</a>\n{plain}'
        limit = self.config.telegram_message_limit
        if len(plain) > limit:
            plain = plain[: max(limit - 10, 1)] + "…"
        payload = {
            "chat_id": chat_id,
            "text": plain,
            "parse_mode": "HTML",
            "disable_web_page_preview": not bool(image_url),
        }
        if markup:
            payload["reply_markup"] = markup
        return await self._call("sendMessage", payload)

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        try:
            result = await self._call("getUpdates", payload)
        except httpx.ReadTimeout:
            return []
        return result or []
