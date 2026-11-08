"""Повідомлення адміну: щоденний звіт, збої з підказками, відновлення, нотатки про публікації."""
import asyncio
from datetime import date, datetime, timedelta

import aiohttp
import pytest
from ua_outages.models import KYIV

from bot import admin as adm
from bot import main as bot_main
from bot.demo import sample_schedule
from bot.telegram import TelegramError

TODAY = date(2026, 11, 8)


def at(hour, day=TODAY):
    return datetime(day.year, day.month, day.day, hour, 7, tzinfo=KYIV)


class Env:
    """Один «запуск бота» без мережі: підміняємо час і джерело, читаємо вивід dry-run."""

    def __init__(self, monkeypatch, tmp_path, capsys):
        self.mp, self.capsys = monkeypatch, capsys
        monkeypatch.setenv("DRY_RUN", "1")
        monkeypatch.setenv("ADMIN_CHAT_ID", "42")
        monkeypatch.delenv("ADMIN_NOTES", raising=False)
        monkeypatch.setattr(bot_main, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(bot_main, "OUT_DIR", tmp_path / "out")
        monkeypatch.setattr(bot_main, "SITE_PATH", tmp_path / "docs" / "index.html")

    def run(self, hour=9, result=None, error=None, day=TODAY):
        async def fake(_now):
            if error:
                raise error
            return result if result is not None else {day: sample_schedule(day)}

        self.mp.setattr(bot_main, "fetch_schedules", fake)
        self.mp.setattr(bot_main, "now_kyiv", lambda: at(hour, day))
        code = asyncio.run(bot_main.run())
        return code, self.capsys.readouterr().out


@pytest.fixture
def env(monkeypatch, tmp_path, capsys):
    return Env(monkeypatch, tmp_path, capsys)


def test_daily_status_once_per_day_and_not_before_8(env):
    _, out = env.run(hour=7)
    assert "Бот працює нормально" not in out
    _, out = env.run(hour=9)
    assert "Бот працює нормально" in out and "сьогодні ✅" in out and "норма ≈144" in out
    _, out = env.run(hour=10)
    assert "Бот працює нормально" not in out
    _, out = env.run(hour=9, day=TODAY + timedelta(days=1), result={TODAY + timedelta(days=1): sample_schedule(TODAY + timedelta(days=1))})
    assert "Бот працює нормально" in out


def test_publication_note_and_switch_off(env, monkeypatch):
    _, out = env.run(hour=7)
    assert "Опубліковано в каналі" in out and "новий графік" in out
    monkeypatch.setenv("ADMIN_NOTES", "0")
    changed = {TODAY: sample_schedule(TODAY, {"1.1": [(0, 2), (4, 8)]})}
    _, out = env.run(hour=7, result=changed)
    assert "Графік оновлено" in out and "Опубліковано в каналі" not in out


def test_failure_alert_once_then_recovery(env, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/bot")
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    env.run(hour=7)  # є стан
    err = aiohttp.ClientConnectionError("boom")
    codes, outs = [], []
    for _ in range(3):
        c, o = env.run(hour=9, error=err)
        codes.append(c), outs.append(o)
    assert codes == [0, 0, 1]
    assert "Бот не може оновити графік" not in outs[0] + outs[1]
    alert = outs[2]
    assert "Бот не може оновити графік" in alert and "Сайт обленерго не відповідає" in alert
    assert "https://github.com/me/bot/actions/runs/777" in alert and "Що робити" in alert
    _, out = env.run(hour=9, error=err)  # 4-й збій: тихо
    assert "Бот не може оновити графік" not in out
    _, out = env.run(hour=9)
    assert "Знову працює" in out and "було: 4" in out
    _, out = env.run(hour=9)
    assert "Знову працює" not in out


def test_unexpected_error_is_reported_and_reraised(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("щось зламалось")

    monkeypatch.setattr(bot_main, "diff_schedules", boom)
    with pytest.raises(RuntimeError):
        env.run(hour=7)
    out = env.capsys.readouterr().out
    assert "Неочікувана помилка" in out


def test_classify_and_throttle():
    assert adm.classify(aiohttp.ClientConnectionError("x")) == adm.SITE
    assert adm.classify(asyncio.TimeoutError()) == adm.SITE
    assert adm.classify(TelegramError("sendMessage: Forbidden")) == adm.TELEGRAM
    assert adm.classify(KeyError("groups")) == adm.PARSE
    assert adm.classify(RuntimeError("???")) == adm.UNKNOWN
    state, now = {}, at(9)
    assert adm.should_notify(state, "k", now)
    assert not adm.should_notify(state, "k", now + timedelta(hours=5))
    assert adm.should_notify(state, "k", now + timedelta(hours=7))


def test_parse_chats_removes_duplicates():
    assert bot_main.parse_chats("@Chan, @chan ,-1001;-1001,,-1002") == ["@chan", "-1001", "-1002"]
    assert bot_main.parse_chats("") == []


def test_daily_mentions_number_of_chats(env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@a,@A,-1")
    _, out = env.run(hour=9)
    assert "Публікую в чатів: 2" in out
