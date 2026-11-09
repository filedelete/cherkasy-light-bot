"""Мінімальний клієнт Telegram Bot API (sendMessage, pinChatMessage, unpinChatMessage, deleteMessage)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import aiohttp

API = "https://api.telegram.org/bot{token}/{method}"


LIMIT = 4096  # максимум символів в одному повідомленні Telegram


class TelegramError(RuntimeError):
    pass


def split_text(text: str, limit: int = LIMIT) -> list[str]:
    """Ріже довгий текст між блоками (порожній рядок або кінець картки), не розриваючи теги."""
    if len(text) <= limit:
        return [text]
    blocks = re.split(r"(?<=</blockquote>)\n|\n\n", text)
    parts, cur = [], ""
    for block in blocks:
        if cur and len(cur) + 1 + len(block) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n{block}" if cur else block
    parts.append(cur)
    return parts


class Telegram:
    def __init__(self, session: aiohttp.ClientSession, token: str, chat_ids: list[str],
                 *, dry_run: bool = False, out_dir: Path = Path("out"), button_url: str = ""):
        self.session, self.token, self.chat_ids = session, token, chat_ids
        self.dry_run, self.out_dir, self._n = dry_run, out_dir, 0
        self.button_url = button_url
        self.pin_errors: list[str] = []
        self.send_errors: list[str] = []  # чати, куди не вдалося надіслати (решта чатів отримала)

    def _markup(self) -> dict:
        """Кнопка «Відкрити сайт» під повідомленням (порожньо, якщо адреси сайту немає)."""
        if not self.button_url:
            return {}
        keyboard = {"inline_keyboard": [[{"text": "🌐 Відкрити сайт", "url": self.button_url}]]}
        return {"reply_markup": json.dumps(keyboard)}

    async def _call(self, method: str, data: aiohttp.FormData | dict, retries: int = 3) -> dict:
        url = API.format(token=self.token, method=method)
        for attempt in range(retries):
            async with self.session.post(url, data=data) as resp:
                body = await resp.json(content_type=None)
            if body.get("ok"):
                return body.get("result") or {}
            if body.get("error_code") == 429 and attempt < retries - 1:
                await asyncio.sleep(body.get("parameters", {}).get("retry_after", 5) + 1)
                continue
            raise TelegramError(f"{method}: {body.get('description', body)}")

    async def updates(self, offset: int) -> list[dict]:
        """Нові повідомлення боту (команди). У dry-run мережі немає."""
        if self.dry_run:
            return []
        result = await self._call("getUpdates", {"offset": offset, "timeout": 0, "limit": 100,
                                                 "allowed_updates": json.dumps(["message"])})
        return list(result or [])

    async def reply(self, chat_id: int | str, text: str, *, with_button: bool = False) -> None:
        """Відповідь в один конкретний чат (а не в усі канали зі списку)."""
        parts = split_text(text)
        for i, part in enumerate(parts):
            if self.dry_run:
                self._dump(f"[відповідь у {chat_id}]\n{part}")
                continue
            extra = self._markup() if with_button and i == len(parts) - 1 else {}
            await self._call("sendMessage", {"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                                              "disable_web_page_preview": "true", **extra})

    async def message(self, text: str) -> dict[str, int]:
        """Надсилає текст у всі чати. Повертає {chat_id: id останнього надісланого повідомлення}.

        Чати незалежні: якщо в одному збій (бота видалили з групи), решта все одно отримує повідомлення.
        Виняток лише коли не вдалося жодному чату, тоді публікацію буде повторено наступного разу.
        """
        parts = split_text(text)
        ids: dict[str, int] = {}
        failed: dict[str, Exception] = {}
        for i, part in enumerate(parts):
            if self.dry_run:
                self._dump(part + (f"\n[кнопка: {self.button_url}]" if self.button_url and i == len(parts) - 1 else ""))
                continue
            extra = self._markup() if i == len(parts) - 1 else {}
            for chat in self.chat_ids:
                if chat in failed:
                    continue
                try:
                    sent = await self._call("sendMessage", {"chat_id": chat, "text": part, "parse_mode": "HTML",
                                                             "disable_web_page_preview": "true", **extra})
                except Exception as err:  # noqa: BLE001
                    failed[chat] = err
                    continue
                ids[chat] = sent.get("message_id", 0)
        if self.dry_run:
            return {chat: 0 for chat in (self.chat_ids or ["dry-run"])}
        if failed and not ids:
            raise next(iter(failed.values()))
        for chat, err in failed.items():
            self.send_errors.append(f"{chat}: {err}")
            print(f"Не вдалося надіслати в {chat}: {err!r}; інші чати отримали повідомлення")
        return ids

    async def pin_latest(self, ids: dict[str, int], previous: dict[str, int]) -> dict[str, int]:
        """Закріплює щойно надіслане повідомлення, а попереднє закріплене ботом відкріплює.

        ids: {chat: id нового}; previous: {chat: id закріпленого раніше}. Повертає актуальний {chat: id}.
        Помилки не переривають роботу, а потрапляють у self.pin_errors.
        """
        self.pin_errors = []
        if self.dry_run:
            self._dump("[закріплено це повідомлення]")
            return dict(ids)
        result = dict(previous)
        for chat, mid in ids.items():
            try:
                await self._call("pinChatMessage", {"chat_id": chat, "message_id": mid, "disable_notification": "true"})
            except TelegramError as err:
                self.pin_errors.append(f"{chat}: {err}")
                print(f"Не вдалося закріпити у {chat}: {err}. Дайте боту право «Закріплювати повідомлення».")
                continue
            old = previous.get(chat)
            if old and old != mid:
                try:
                    await self._call("unpinChatMessage", {"chat_id": chat, "message_id": old})
                except TelegramError:
                    pass  # старе могли відкріпити чи видалити вручну
            result[chat] = mid
        return result

    async def remove_pinned(self, ids: dict[str, int]) -> None:
        """Видаляє застарілий окремий пост «Актуальний графік» (з ранніх версій бота)."""
        for chat, mid in ids.items():
            if self.dry_run:
                self._dump(f"[видалено застарілий закріплений пост {mid} у {chat}]")
                continue
            try:
                await self._call("deleteMessage", {"chat_id": chat, "message_id": mid})
            except TelegramError as err:
                print(f"Не вдалося видалити застарілий пост у {chat}: {err}. Видаліть його вручну.")

    def _dump(self, text: str) -> None:
        self._n += 1
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"message_{self._n}.html").write_text(text, encoding="utf-8")
        print(f"[dry-run] повідомлення {self._n}")
        print(text, "\n")
