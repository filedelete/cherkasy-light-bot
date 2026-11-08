"""Мінімальний клієнт Telegram Bot API (sendMessage)."""
from __future__ import annotations

import asyncio
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
                 *, dry_run: bool = False, out_dir: Path = Path("out")):
        self.session, self.token, self.chat_ids = session, token, chat_ids
        self.dry_run, self.out_dir, self._n = dry_run, out_dir, 0

    async def _call(self, method: str, data: aiohttp.FormData | dict, retries: int = 3) -> None:
        url = API.format(token=self.token, method=method)
        for attempt in range(retries):
            async with self.session.post(url, data=data) as resp:
                body = await resp.json(content_type=None)
            if body.get("ok"):
                return
            if body.get("error_code") == 429 and attempt < retries - 1:
                await asyncio.sleep(body.get("parameters", {}).get("retry_after", 5) + 1)
                continue
            raise TelegramError(f"{method}: {body.get('description', body)}")

    async def message(self, text: str) -> None:
        for part in split_text(text):
            if self.dry_run:
                self._dump(part)
                continue
            for chat in self.chat_ids:
                await self._call("sendMessage", {"chat_id": chat, "text": part, "parse_mode": "HTML",
                                                  "disable_web_page_preview": "true"})

    def _dump(self, text: str) -> None:
        self._n += 1
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"message_{self._n}.html").write_text(text, encoding="utf-8")
        print(f"[dry-run] повідомлення {self._n}")
        print(text, "\n")
