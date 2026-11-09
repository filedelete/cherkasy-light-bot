"""Одне повідомлення про графік: надсилається й закріплюється, попереднє відкріплюється."""
import asyncio

from bot import main as bot_main
from bot.demo import sample_schedule
from bot.telegram import Telegram, TelegramError
from test_admin import TODAY, env  # noqa: F401


class Fake(Telegram):
    def __init__(self, fail=None):
        super().__init__(None, "t", ["@c"])
        self.calls, self.fail, self.n = [], fail, 100

    async def _call(self, method, data, retries=3):
        self.calls.append((method, data.get("message_id")))
        if self.fail and method == self.fail:
            raise TelegramError(f"{method}: Bad Request: not enough rights")
        self.n += 1
        return {"message_id": self.n}


def test_message_returns_id_and_pin_replaces_previous():
    tg = Fake()
    ids = asyncio.run(tg.message("графік"))
    assert ids == {"@c": 101}
    pinned = asyncio.run(tg.pin_latest(ids, {}))
    assert pinned == {"@c": 101} and tg.calls == [("sendMessage", None), ("pinChatMessage", 101)]
    tg.calls.clear()
    ids2 = asyncio.run(tg.message("оновлений графік"))
    pinned2 = asyncio.run(tg.pin_latest(ids2, pinned))
    assert pinned2 == {"@c": 103}   # id: 101 повідомлення, 102 виклик закріплення, 103 нове повідомлення
    assert tg.calls == [("sendMessage", None), ("pinChatMessage", 103), ("unpinChatMessage", 101)]


def test_long_message_returns_id_of_last_part():
    tg = Fake()
    ids = asyncio.run(tg.message("\n\n".join(["x" * 3000, "y" * 3000])))
    assert ids == {"@c": 102}      # закріплюємо останню частину


def test_pin_error_is_collected_not_raised():
    tg = Fake(fail="pinChatMessage")
    ids = asyncio.run(tg.message("графік"))
    assert asyncio.run(tg.pin_latest(ids, {"@c": 7})) == {"@c": 7}   # стан не псується
    assert len(tg.pin_errors) == 1 and "not enough rights" in tg.pin_errors[0]


def test_flow_prints_pin_and_can_be_switched_off(env, monkeypatch):
    _, out = env.run(hour=7)
    assert "Опубліковано новий графік" in out and "[закріплено це повідомлення]" in out
    assert out.count("АКТУАЛЬНИЙ ГРАФІК") == 0          # окремого поста немає
    monkeypatch.setenv("PIN_MESSAGE", "0")
    changed = {TODAY: sample_schedule(TODAY, {"1.1": [(0, 2), (4, 8)]})}
    _, out = env.run(hour=7, result=changed)
    assert "Графік оновлено" in out and "[закріплено це повідомлення]" not in out


def test_one_message_per_publication_only(env):
    """Новий графік = рівно одне повідомлення в канал (плюс нотатка адміну), без другого поста."""
    _, out = env.run(hour=7)
    assert out.count("ГРАФІК ВІДКЛЮЧЕНЬ") == 1


def test_legacy_separate_pinned_post_is_deleted(env):
    env.run(hour=7)
    st = bot_main.load_state()
    st["pinned"], st["pinned_day"] = {"@c": 55}, "2026-11-08"   # залишок від ранньої версії
    bot_main.save_state(st)
    _, out = env.run(hour=7)
    assert "видалено застарілий закріплений пост 55" in out
    assert "pinned" not in bot_main.load_state()
