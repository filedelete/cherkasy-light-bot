"""Команди /ping і /graf в особистих повідомленнях."""
import asyncio
from datetime import date

import pytest

from bot import commands
from bot import main as bot_main
from bot.demo import sample_schedule
from bot.telegram import Telegram
from tests.test_admin import TODAY, at, Env


def upd(i, text, chat_type="private", chat_id=7):
    return {"update_id": i, "message": {"text": text, "chat": {"id": chat_id, "type": chat_type}}}


@pytest.mark.parametrize("text,cmd", [("/ping", "ping"), ("/PING@MyBot", "ping"), ("Пінг", "ping"),
                                      ("/graf", "graf"), ("граф", "graf"), ("/графік", "graf"),
                                      ("привіт", None), ("", None)])
def test_command_of(text, cmd):
    assert commands.command_of(text) == cmd


@pytest.fixture
def env(monkeypatch, tmp_path, capsys):
    return Env(monkeypatch, tmp_path, capsys)


def feed(monkeypatch, updates):
    async def fake(self, offset):
        return [u for u in updates if u["update_id"] >= offset]
    monkeypatch.setattr(Telegram, "updates", fake)


def test_ping_and_graf_only_in_private(env, monkeypatch):
    env.run(hour=7)  # у стані з'являється графік
    feed(monkeypatch, [upd(1, "/ping"), upd(2, "/graf"), upd(3, "/ping", "supergroup", -5), upd(4, "hello")])
    _, out = env.run(hour=9)
    assert out.count("Понг!") == 1 and "Бот працює." in out
    assert "АКТУАЛЬНИЙ ГРАФІК" in out and "відповідь у 7" in out
    assert "-5" not in out.split("Понг!")[0]  # групу ігноруємо


def test_offset_prevents_repeat_answers(env, monkeypatch):
    env.run(hour=7)
    feed(monkeypatch, [upd(10, "/ping")])
    _, out = env.run(hour=9)
    assert "Понг!" in out
    _, out = env.run(hour=9)
    assert "Понг!" not in out


def test_graf_without_schedule(env, monkeypatch):
    feed(monkeypatch, [upd(1, "/graf")])
    state = {}
    asyncio.run(commands.process(state, token="x", now=at(9), dry_run=True))
    assert state["update_offset"] == 2


def test_graf_text_empty_state():
    assert "ще немає" in commands.graf_text({}, at(9))


def test_failure_in_commands_does_not_break_run(env, monkeypatch):
    async def boom(self, offset):
        raise RuntimeError("409 conflict")
    monkeypatch.setattr(Telegram, "updates", boom)
    code, out = env.run(hour=9)
    assert code == 0 and "Не вдалося обробити команди" in out
