"""Кнопка «Відкрити сайт»: адреса з GITHUB_REPOSITORY і вкладення до повідомлень."""
import asyncio
import json

from bot import main as bot_main
from bot.telegram import Telegram


class Fake(Telegram):
    def __init__(self, url="https://u.github.io/r/"):
        super().__init__(None, "t", ["@c"], button_url=url)
        self.sent = []

    async def _call(self, method, data, retries=3):
        self.sent.append((method, data))
        return {"message_id": 5}


def test_site_url_from_repository(monkeypatch):
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "FileDelete/cherkasy-light-bot")
    assert bot_main.site_url() == "https://filedelete.github.io/cherkasy-light-bot/"
    monkeypatch.setenv("GITHUB_REPOSITORY", "filedelete/filedelete.github.io")
    assert bot_main.site_url() == "https://filedelete.github.io/"
    monkeypatch.setenv("SITE_URL", "https://example.com/x/")
    assert bot_main.site_url() == "https://example.com/x/"
    monkeypatch.setenv("SITE", "0")
    assert bot_main.site_url() == ""
    monkeypatch.delenv("SITE"); monkeypatch.delenv("SITE_URL"); monkeypatch.delenv("GITHUB_REPOSITORY")
    assert bot_main.site_url() == ""


def test_button_only_on_last_part_and_on_pinned():
    tg = Fake()
    asyncio.run(tg.message("\n\n".join(["x" * 3000, "y" * 3000])))
    assert len(tg.sent) == 2
    assert "reply_markup" not in tg.sent[0][1] and "reply_markup" in tg.sent[1][1]
    markup = json.loads(tg.sent[1][1]["reply_markup"])
    assert markup["inline_keyboard"][0][0]["url"] == "https://u.github.io/r/"

    pin = Fake(); asyncio.run(pin.pinned("x", {}))                    # новий пост
    assert all("reply_markup" in d for m, d in pin.sent if m == "sendMessage")
    edit = Fake(); asyncio.run(edit.pinned("x", {"@c": 5}))           # редагування
    assert "reply_markup" in edit.sent[0][1]


def test_no_button_without_url():
    tg = Fake(url="")
    asyncio.run(tg.message("hi"))
    assert "reply_markup" not in tg.sent[0][1]
