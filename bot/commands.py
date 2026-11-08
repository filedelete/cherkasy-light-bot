"""Команди в особистих повідомленнях боту: /ping і /graf.

Бот запускається за розкладом, а не працює постійно, тому на початку кожного запуску
він забирає нові повідомлення (getUpdates) і відповідає на них. Відповідь приходить
у межах одного інтервалу запуску (до ≈10 хв). Група й канал ігноруються: лише приват.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import aiohttp
from ua_outages.models import DaySchedule

from . import message
from .telegram import Telegram

PING = {"ping", "пінг", "пинг"}
GRAF = {"graf", "grafik", "граф", "графік", "графіки", "график"}


def command_of(text: str) -> str | None:
    """«/ping», «/graf@MyBot», «Граф» → 'ping' | 'graf' | None."""
    words = (text or "").strip().lower().split()
    if not words:
        return None
    word = words[0].lstrip("/").split("@")[0]
    if word in PING:
        return "ping"
    if word in GRAF:
        return "graf"
    return None


def ping_text(state: dict, now: datetime) -> str:
    last = state.get("last_ok")
    extra = ""
    if last:
        try:
            extra = f"\n🕒 Остання вдала перевірка графіка: {datetime.fromisoformat(last):%d.%m о %H:%M}"
        except ValueError:
            pass
    return f"🏓 <b>Понг!</b> Бот працює.{extra}"


def graf_text(state: dict, now: datetime) -> str:
    schedules = {date.fromisoformat(k): DaySchedule.from_dict(v) for k, v in state.get("schedules", {}).items()}
    if not any(d >= now.date() for d in schedules):
        return "⏳ Графіка в боті ще немає. Як тільки оператор його опублікує, він з'явиться тут."
    return message.pinned(schedules, now)


async def process(state: dict, *, token: str, now: datetime, dry_run: bool = False,
                  out_dir: Path = Path("out"), button_url: str = "") -> int:
    """Відповісти на нові команди. Повертає кількість відповідей. Збої не ламають основний запуск."""
    if not token and not dry_run:
        return 0
    answered = 0
    try:
        async with aiohttp.ClientSession() as session:
            tg = Telegram(session, token, [], dry_run=dry_run, out_dir=out_dir, button_url=button_url)
            offset = state.get("update_offset", 0)
            updates = await tg.updates(offset)
            print(f"Команди: нових повідомлень боту {len(updates)}")
            for upd in updates:
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                cmd = command_of(msg.get("text", "")) if chat.get("type") == "private" else None
                if cmd:
                    text = ping_text(state, now) if cmd == "ping" else graf_text(state, now)
                    await tg.reply(chat["id"], text, with_button=cmd == "graf")
                    answered += 1
                offset = max(offset, upd["update_id"] + 1)
                state["update_offset"] = offset
    except Exception as err:  # noqa: BLE001  (наприклад, 409, якщо в бота ще встановлено вебхук)
        print(f"Не вдалося обробити команди: {err!r}")
    return answered
