"""Закріплений пост «Актуальний графік»: текст і логіка edit / send+pin (без мережі)."""
import asyncio
from datetime import date, datetime

from ua_outages.models import KYIV

from bot import message
from bot.demo import sample_schedule
from bot.telegram import Telegram, TelegramError

NOW = datetime(2026, 11, 8, 14, 10, tzinfo=KYIV)


def test_pinned_text_today_and_tomorrow():
    today, tomorrow = date(2026, 11, 8), date(2026, 11, 9)
    text = message.pinned({today: sample_schedule(today), tomorrow: sample_schedule(tomorrow)}, NOW)
    assert "АКТУАЛЬНИЙ ГРАФІК" in text and "Сьогодні" in text and "Завтра" in text
    assert "оновлено 14:10" in text and len(text) <= 4096


def test_pinned_skips_past_days():
    yesterday = date(2026, 11, 7)
    text = message.pinned({yesterday: sample_schedule(yesterday), date(2026, 11, 8): sample_schedule()}, NOW)
    assert "Вчора" not in text and "7 листопада" not in text


class Fake(Telegram):
    def __init__(self, fail_edit: str | None = None):
        super().__init__(None, "t", ["@c"])
        self.calls, self.fail_edit = [], fail_edit

    async def _call(self, method, data, retries=3):
        self.calls.append(method)
        if method == "editMessageText" and self.fail_edit:
            raise TelegramError(f"{method}: {self.fail_edit}")
        return {"message_id": 42}


def test_pinned_first_send_and_pin_then_edit():
    tg = Fake()
    ids = asyncio.run(tg.pinned("x", {}))
    assert ids == {"@c": 42} and tg.calls == ["sendMessage", "pinChatMessage"]
    tg.calls.clear()
    assert asyncio.run(tg.pinned("y", ids)) == ids and tg.calls == ["editMessageText"]


def test_pinned_not_modified_is_fine_but_lost_message_is_resent():
    same = Fake("Bad Request: message is not modified")
    assert asyncio.run(same.pinned("x", {"@c": 7})) == {"@c": 7} and same.calls == ["editMessageText"]
    lost = Fake("Bad Request: message to edit not found")
    assert asyncio.run(lost.pinned("x", {"@c": 7})) == {"@c": 42}
    assert lost.calls == ["editMessageText", "sendMessage", "pinChatMessage"]


def test_pinned_temporary_error_does_not_spawn_duplicates():
    tg = Fake("Too Many Requests")
    try:
        asyncio.run(tg.pinned("x", {"@c": 7}))
        raise AssertionError("мало бути виключення")
    except TelegramError:
        pass
    assert tg.calls == ["editMessageText"]
