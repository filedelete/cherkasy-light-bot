"""Мінімальний клієнт Telegram Bot API (sendMessage, editMessageText, pinChatMessage)."""
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

    async def message(self, text: str) -> None:
        parts = split_text(text)
        for i, part in enumerate(parts):
            if self.dry_run:
                self._dump(part + (f"\n[кнопка: {self.button_url}]" if self.button_url and i == len(parts) - 1 else ""))
                continue
            extra = self._markup() if i == len(parts) - 1 else {}
            for chat in self.chat_ids:
                await self._call("sendMessage", {"chat_id": chat, "text": part, "parse_mode": "HTML",
                                                  "disable_web_page_preview": "true", **extra})

    async def pinned(self, text: str, ids: dict[str, int]) -> dict[str, int]:
        """Закріплений пост «Актуальний графік»: редагує наявний, інакше надсилає новий і закріплює.

        ids: {chat_id: message_id} з минулих запусків; повертає оновлений словник.
        """
        if self.dry_run:
            self._dump("[закріплене повідомлення]\n" + text + (f"\n[кнопка: {self.button_url}]" if self.button_url else ""))
            return ids
        result = dict(ids)
        for chat in self.chat_ids:
            mid = ids.get(chat)
            if mid:
                try:
                    await self._call("editMessageText", {"chat_id": chat, "message_id": mid, "text": text,
                                                         "parse_mode": "HTML", "disable_web_page_preview": "true",
                                                         **self._markup()})
                    continue
                except TelegramError as err:
                    msg = str(err).lower()
                    if "not modified" in msg:
                        continue
                    if not any(k in msg for k in ("not found", "can't be edited", "message_id_invalid")):
                        raise  # тимчасова помилка: спробуємо ще раз, а не плодимо нові пости
            sent = await self._call("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML",
                                                    "disable_web_page_preview": "true",
                                                    "disable_notification": "true", **self._markup()})
            result[chat] = sent["message_id"]
            try:
                await self._call("pinChatMessage", {"chat_id": chat, "message_id": sent["message_id"],
                                                    "disable_notification": "true"})
            except TelegramError as err:
                print(f"Не вдалося закріпити у {chat}: {err}. Дайте боту право «Закріплювати повідомлення».")
        return result

    def _dump(self, text: str) -> None:
        self._n += 1
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"message_{self._n}.html").write_text(text, encoding="utf-8")
        print(f"[dry-run] повідомлення {self._n}")
        print(text, "\n")
