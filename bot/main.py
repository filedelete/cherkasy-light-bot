"""Перевіряє графік Черкасиобленерго і постить у Telegram, коли він з'явився або змінився."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import aiohttp
from ua_outages import Fetcher, now_kyiv, operator
from ua_outages.http import new_session
from ua_outages.models import DaySchedule
from ua_outages.timeline import diff_schedules

from . import message
from .telegram import Telegram

OPERATOR_ID = "cherkasy-oe"
STATE_PATH = Path(os.environ.get("STATE_PATH", "state/state.json"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))
FAIL_ALERT_AFTER = 6  # поспіль невдалих перевірок (≈1 година при кроці 10 хв)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


async def fetch_schedules(now) -> dict[date, DaySchedule]:
    op = operator(OPERATOR_ID)
    source = op.sources[0]
    async with new_session() as session:
        return await source.fetch(Fetcher(session, source.hosts), now)


def env_flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).strip().lower() in {"1", "true", "yes"}


async def run() -> int:
    dry_run = env_flag("DRY_RUN")
    post_first = env_flag("POST_ON_FIRST_RUN", True)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if not dry_run and (not token or not chats):
        print("Не задано TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID (Settings → Secrets → Actions).")
        return 2

    now = now_kyiv()
    state = load_state()
    first_run = "schedules" not in state

    try:
        new = await fetch_schedules(now)
    except Exception as err:  # мережа, захист сайту, зміна формату
        fails = state.get("fails", 0) + 1
        state["fails"] = fails
        save_state(state)
        print(f"Не вдалося отримати графік ({fails} поспіль): {err!r}")
        if fails == FAIL_ALERT_AFTER:
            async with aiohttp.ClientSession() as s:
                if admin and token and not dry_run:
                    await Telegram(s, token, [admin]).message(
                        f"⚠️ Бот не може отримати графік уже {fails} перевірок поспіль:\n<code>{err!r}</code>"[:900])
            return 1
        return 0

    old = {date.fromisoformat(k): DaySchedule.from_dict(v) for k, v in state.get("schedules", {}).items()}
    old = {d: s for d, s in old.items() if d >= now.date()}
    new = {d: (s.with_missing_from(old[d]) if d in old else s) for d, s in new.items()}

    if not new:
        print("Джерело відповіло, але графіків на сьогодні/завтра ще немає.")
        state["fails"] = 0
        state["heartbeat"] = now.date().isoformat()
        save_state(state)
        return 0

    changes = diff_schedules(old, new)
    result = {d: s for d, s in old.items() if d not in new}  # день міг тимчасово зникнути з відповіді
    result.update(new)

    async with aiohttp.ClientSession() as session:
        tg = Telegram(session, token, chats, dry_run=dry_run, out_dir=OUT_DIR)
        for change in changes:
            sched = change.schedule
            if first_run and not post_first:
                continue
            try:
                if message.no_outages(sched):
                    await tg.message(message.all_clear(sched))
                else:
                    await tg.message(message.build(change))
            except Exception as err:
                print(f"Не вдалося опублікувати {sched.day}: {err!r}; спробую ще раз за наступної перевірки")
                if sched.day in old:
                    result[sched.day] = old[sched.day]
                else:
                    result.pop(sched.day, None)

    state["schedules"] = {d.isoformat(): s.to_dict() for d, s in sorted(result.items())}
    state["fails"] = 0
    state["heartbeat"] = now.date().isoformat()  # раз на добу змінює файл, щоб GitHub не вимкнув розклад
    save_state(state)
    print(f"Готово: змін {len(changes)}, днів у стані {len(result)}.")
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
