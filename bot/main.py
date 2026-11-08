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

from . import admin as adm
from . import commands, message, site, weekly
from .telegram import Telegram

OPERATOR_ID = "cherkasy-oe"
STATE_PATH = Path(os.environ.get("STATE_PATH", "state/state.json"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "out"))
SITE_PATH = Path(os.environ.get("SITE_PATH", "docs/index.html"))  # для GitHub Pages; SITE=0 вимикає
WEEKLY_HOUR = 20        # підсумок тижня публікується в неділю з цієї години
FAIL_ALERT_AFTER = 3    # поспіль невдалих перевірок до сповіщення адміну (≈30 хв при кроці 10 хв)
FAIL_REMIND_EVERY = 36  # нагадувати про незакінчений збій раз на ≈6 годин


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


def site_url() -> str:
    """Адреса сайту на GitHub Pages: SITE_URL, інакше з GITHUB_REPOSITORY (задається в Actions сам)."""
    if not env_flag("SITE", True):
        return ""
    url = os.environ.get("SITE_URL", "").strip()
    if url:
        return url
    owner, _, name = os.environ.get("GITHUB_REPOSITORY", "").partition("/")
    if not owner or not name:
        return ""
    host = f"{owner.lower()}.github.io"
    return f"https://{host}/" + ("" if name.lower() == host else f"{name}/")


def bump(state: dict, key: str) -> None:
    stats = state.setdefault("stats", {})
    stats[key] = stats.get(key, 0) + 1


def parse_chats(raw: str) -> list[str]:
    """TELEGRAM_CHAT_ID → список без повторів (@Назва і @назва — це той самий чат)."""
    seen: dict[str, None] = {}
    for c in raw.replace(";", ",").split(","):
        c = c.strip()
        if c:
            seen.setdefault(c.lower() if c.startswith("@") else c, None)
    return list(seen)


def env_flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).strip().lower() in {"1", "true", "yes"}


async def _run() -> int:
    dry_run = env_flag("DRY_RUN")
    post_first = env_flag("POST_ON_FIRST_RUN", True)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chats = parse_chats(os.environ.get("TELEGRAM_CHAT_ID", ""))
    admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
    notes = env_flag("ADMIN_NOTES", True)  # коротка нотатка адміну після кожної публікації

    async def tell(text: str) -> None:
        await adm.notify(text, token=token, chat=admin, dry_run=dry_run)

    async def daily(now_, days: set[date]) -> None:
        """Раз на добу (з 08:00) — «бот працює нормально» зі статистикою."""
        today_ = now_.date().isoformat()
        if now_.hour >= adm.STATUS_HOUR and state.get("status_day") != today_:
            await tell(adm.daily(now_, state.get("stats", {}), days, len(chats)))
            state["status_day"], state["stats"] = today_, {}
    if not dry_run and (not token or not chats):
        print("Не задано TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID (Settings → Secrets → Actions).")
        return 2

    now = now_kyiv()
    state = load_state()
    first_run = "schedules" not in state

    # команди /ping і /graf в особистих повідомленнях (відповідаємо до перевірки сайту, щоб /ping працював і при збої)
    if await commands.process(state, token=token, now=now, dry_run=dry_run, out_dir=OUT_DIR, button_url=site_url()):
        save_state(state)

    try:
        new = await fetch_schedules(now)
    except Exception as err:  # мережа, захист сайту, зміна формату
        fails = state.get("fails", 0) + 1
        state["fails"] = fails
        bump(state, "checks")
        bump(state, "fails")
        print(f"Не вдалося отримати графік ({fails} поспіль): {err!r}")
        alert = fails == FAIL_ALERT_AFTER or (fails > FAIL_ALERT_AFTER and fails % FAIL_REMIND_EVERY == 0)
        if alert:
            state["alerted"] = True
            await tell(adm.failure(err, fails))
        save_state(state)
        return 1 if alert else 0

    bump(state, "checks")
    prev_fails = state.get("fails", 0)
    if state.pop("alerted", False):
        await tell(adm.recovered(prev_fails))

    old = {date.fromisoformat(k): DaySchedule.from_dict(v) for k, v in state.get("schedules", {}).items()}
    old = {d: s for d, s in old.items() if d >= now.date()}
    new = {d: (s.with_missing_from(old[d]) if d in old else s) for d, s in new.items()}

    if not new:
        print("Джерело відповіло, але графіків на сьогодні/завтра ще немає.")
        state["fails"] = 0
        state["heartbeat"] = now.date().isoformat()
        await daily(now, set(old))
        save_state(state)
        return 0

    changes = diff_schedules(old, new)
    result = {d: s for d, s in old.items() if d not in new}  # день міг тимчасово зникнути з відповіді
    result.update(new)
    weekly.update_history(state, result, now.date())

    async with aiohttp.ClientSession() as session:
        tg = Telegram(session, token, chats, dry_run=dry_run, out_dir=OUT_DIR, button_url=site_url())
        done: list[str] = []
        for change in changes:
            sched = change.schedule
            if first_run and not post_first:
                continue
            try:
                if message.no_outages(sched):
                    await tg.message(message.all_clear(sched))
                else:
                    await tg.message(message.build(change))
                bump(state, "published")
                names = ", ".join(sorted(change.groups))
                done.append(f"{message.date_label(sched.day)}: " + ("новий графік" if change.published else f"оновлено черги {names}"))
            except Exception as err:
                print(f"Не вдалося опублікувати {sched.day}: {err!r}; спробую ще раз за наступної перевірки")
                if adm.should_notify(state, "publish", now):
                    await tell(adm.publish_failed(err, f"опублікувати графік на {message.date_label(sched.day)}"))
                if sched.day in old:
                    result[sched.day] = old[sched.day]
                else:
                    result.pop(sched.day, None)

        # закріплений пост: оновлюємо при змінах, на початку нової доби й коли його ще немає
        today = now.date().isoformat()
        if changes or state.get("pinned_day") != today or not state.get("pinned"):
            try:
                state["pinned"] = await tg.pinned(message.pinned(result, now), state.get("pinned", {}))
                state["pinned_day"] = today
            except Exception as err:
                print(f"Не вдалося оновити закріплений пост: {err!r}; спробую ще раз за наступної перевірки")
                if adm.should_notify(state, "pinned", now):
                    await tell(adm.publish_failed(err, "оновити закріплений пост"))

        # підсумок тижня: у неділю ввечері, раз на тиждень, якщо накопичилось достатньо даних
        week = weekly.week_of(now.date())[0].isoformat()
        if now.weekday() == 6 and now.hour >= WEEKLY_HOUR and state.get("weekly") != week:
            text = weekly.weekly_text(state, now.date())
            if text:
                try:
                    await tg.message(text)
                    state["weekly"] = week
                    bump(state, "published")
                    done.append("підсумок тижня")
                except Exception as err:
                    print(f"Не вдалося опублікувати підсумок тижня: {err!r}")
                    if adm.should_notify(state, "weekly", now):
                        await tell(adm.publish_failed(err, "опублікувати підсумок тижня"))

    if notes and done:
        await tell(adm.published(done))

    # сайт (GitHub Pages): оновлюємо при змінах, раз на добу й коли файлу ще немає
    today = now.date().isoformat()
    if env_flag("SITE", True) and (changes or state.get("site_day") != today or not SITE_PATH.exists()):
        try:
            site.write_site(SITE_PATH, result, now)
            state["site_day"] = today
        except Exception as err:
            print(f"Не вдалося оновити сайт: {err!r}")

    # graf.json для Worker (миттєві команди): лише коли графік змінився, раз на добу або файлу ще немає
    graf_path = SITE_PATH.parent / "graf.json"
    if env_flag("SITE", True) and (changes or state.get("graf_day") != today or not graf_path.exists()):
        try:
            commands.write_graf(graf_path, result, now)
            state["graf_day"] = today
        except Exception as err:
            print(f"Не вдалося записати graf.json: {err!r}")

    await daily(now, set(result))
    state["schedules"] = {d.isoformat(): s.to_dict() for d, s in sorted(result.items())}
    state["fails"] = 0
    state["last_ok"] = now.isoformat()
    state["heartbeat"] = now.date().isoformat()  # раз на добу змінює файл, щоб GitHub не вимкнув розклад
    save_state(state)
    print(f"Готово: змін {len(changes)}, днів у стані {len(result)}.")
    return 0


async def run() -> int:
    """_run() із захистом: будь-який непередбачений збій потрапляє адміну, а не пропадає в журналі."""
    try:
        return await _run()
    except Exception as err:  # noqa: BLE001
        print(f"Неочікувана помилка: {err!r}")
        state = load_state()
        if adm.should_notify(state, "unexpected", now_kyiv()):
            save_state(state)
            await adm.notify(adm.unexpected(err), token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                             chat=os.environ.get("ADMIN_CHAT_ID", "").strip(), dry_run=env_flag("DRY_RUN"))
        raise


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
