"""Повідомлення адміну (вам у приват): «все гаразд», збої з підказками, що робити.

Надсилаються лише якщо задано ADMIN_CHAT_ID. Бот не може повідомити про власну
відсутність: якщо щоденне «✅ Бот працює» перестало приходити, бот не запускається,
і треба зайти у вкладку Actions.
"""
from __future__ import annotations

import asyncio
import os
import traceback
from datetime import date, datetime, timedelta
from html import escape

import aiohttp

from .telegram import Telegram, TelegramError

STATUS_HOUR = 8              # щоденний звіт «все гаразд» — з цієї години за Києвом
EXPECTED_CHECKS = 144        # перевірок на добу при кроці 10 хвилин
THROTTLE_HOURS = 6           # як часто повторювати однакове попередження


# ---------- де шукати ----------

def links() -> dict[str, str]:
    """Посилання на журнал запуску й налаштування (у GitHub Actions вони відомі автоматично)."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not repo:
        return {}
    base = f"{server}/{repo}"
    out = {"actions": f"{base}/actions", "secrets": f"{base}/settings/secrets/actions"}
    if run_id:
        out["run"] = f"{base}/actions/runs/{run_id}"
    return out


def _where(*keys: str) -> str:
    names = {"run": "Журнал цього запуску", "actions": "Усі запуски (Actions)", "secrets": "Секрети (токен, chat_id)"}
    lk = links()
    lines = [f'🔎 <a href="{lk[k]}">{names[k]}</a>' for k in keys if k in lk]
    return "\n".join(lines) if lines else "🔎 Дивіться вікно, у якому запущено бота"


# ---------- класифікація помилок ----------

SITE, PARSE, TELEGRAM, UNKNOWN = "site", "parse", "telegram", "unknown"

HINTS = {
    SITE: ("Сайт обленерго не відповідає або не пускає бота",
           ["Відкрийте сайт Черкасиобленерго у браузері. Якщо він не відкривається, це їхня проблема, бот сам відновиться, коли сайт запрацює.",
            "Якщо сайт відкривається, а бот не може його прочитати: сервери GitHub можуть бути заблоковані. Надішліть Claude текст помилки з журналу, він запропонує запасний варіант (запуск на ПК чи в Україні).",
            "Одиничні збої (таймаут, 5xx) минають самі, хвилюватись не треба."]),
    PARSE: ("Сторінка оператора, схоже, змінила формат, і бот її не розуміє",
            ["Відкрийте журнал запуску за посиланням нижче й скопіюйте текст помилки.",
             "Надішліть його Claude з фразою «бот перестав читати графік»: потрібно оновити читання сторінки.",
             "Поки що бот просто не публікує нових змін, старі повідомлення в каналі лишаються."]),
    TELEGRAM: ("Telegram не приймає повідомлення від бота",
               ["Перевірте, що бот досі адміністратор каналу з правами публікувати, редагувати й закріплювати повідомлення.",
                "Якщо ви робили /revoke у @BotFather, оновіть секрет TELEGRAM_BOT_TOKEN на новий токен.",
                "Перевірте TELEGRAM_CHAT_ID (для публічного каналу це @назва, для приватного число з -100)."]),
    UNKNOWN: ("Неочікувана помилка",
              ["Відкрийте журнал запуску за посиланням нижче й скопіюйте останні рядки.",
               "Надішліть їх Claude, і він підкаже, що виправити."]),
}


def classify(err: BaseException) -> str:
    text = f"{type(err).__name__} {err}".lower()
    if isinstance(err, TelegramError) or "telegram" in text:
        return TELEGRAM
    if (isinstance(err, (asyncio.TimeoutError, aiohttp.ClientError, OSError))
            or any(k in text for k in ("timeout", "connect", "ssl", "403", "429", "502", "503", "504", "forbidden", "refused"))):
        return SITE
    if isinstance(err, (ValueError, KeyError, IndexError, AttributeError, TypeError)) or "parse" in text:
        return PARSE
    return UNKNOWN


def _steps(kind: str) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(HINTS[kind][1], 1))


# ---------- тексти ----------

def failure(err: BaseException, fails: int, minutes_per_check: int = 10) -> str:
    kind = classify(err)
    title, _ = HINTS[kind]
    short = escape(repr(err))[:400]
    return (f"🚨 <b>Бот не може оновити графік</b>\n\n"
            f"<b>Що сталося:</b> {title}\n"
            f"<b>Скільки триває:</b> ≈{fails * minutes_per_check} хв (невдалих перевірок поспіль: {fails})\n"
            f"<b>Помилка:</b> <code>{short}</code>\n\n"
            f"<b>Де шукати:</b>\n{_where('run', 'actions')}\n\n"
            f"<b>Що робити:</b>\n{_steps(kind)}\n\n"
            f"<i>Нові повідомлення в канал поки не надходять. Коли все відновиться, я напишу.</i>")


def publish_failed(err: BaseException, what: str) -> str:
    kind = TELEGRAM if classify(err) in (TELEGRAM, SITE) else classify(err)
    short = escape(repr(err))[:400]
    return (f"⚠️ <b>Не вдалося {what}</b>\n\n"
            f"<b>Помилка:</b> <code>{short}</code>\n\n"
            f"<b>Де шукати:</b>\n{_where('run', 'secrets')}\n\n"
            f"<b>Що робити:</b>\n{_steps(kind)}\n\n"
            f"<i>Бот спробує ще раз за наступної перевірки.</i>")


def unexpected(err: BaseException) -> str:
    tb = "".join(traceback.format_exception_only(type(err), err)).strip()
    last = "\n".join(traceback.format_exc().strip().splitlines()[-6:])
    return (f"🚨 <b>Неочікувана помилка в боті</b>\n\n"
            f"<code>{escape(tb)[:300]}</code>\n\n"
            f"<b>Де шукати:</b>\n{_where('run', 'actions')}\n\n"
            f"<b>Що робити:</b>\n{_steps(UNKNOWN)}\n\n<code>{escape(last)[:700]}</code>")


def recovered(fails: int) -> str:
    return f"✅ <b>Знову працює</b>\nГрафік отримано. Невдалих перевірок поспіль було: {fails}."


def published(items: list[str]) -> str:
    return "📤 <b>Опубліковано в каналі</b>\n" + "\n".join(f"• {i}" for i in items)


def daily(now: datetime, stats: dict, days: set[date], chats: int = 0) -> str:
    today = now.date()
    have = lambda d: "✅" if d in days else "⏳ ще немає"  # noqa: E731
    checks = stats.get("checks", 0)
    ok = "✅" if stats.get("fails", 0) == 0 else "⚠️"
    return (f"✅ <b>Бот працює нормально</b>\n"
            f"🕒 Остання перевірка: {now:%H:%M}\n\n"
            f"📅 Графік у боті: сьогодні {have(today)} · завтра {have(today + timedelta(days=1))}\n"
            f"📊 З минулого звіту: перевірок {checks} (норма ≈{EXPECTED_CHECKS}), "
            f"публікацій {stats.get('published', 0)}, збоїв {stats.get('fails', 0)} {ok}\n"
            + (f"📡 Публікую в чатів: {chats}\n" if chats else "") + "\n"
            f"<i>Щодня близько {STATUS_HOUR}:00 приходить це повідомлення. Якщо його немає, "
            f"бот не запускається: відкрийте вкладку Actions у репозиторії.</i>")


# ---------- відправка ----------

def should_notify(state: dict, kind: str, now: datetime, hours: int = THROTTLE_HOURS) -> bool:
    """Не повторювати однакове попередження частіше, ніж раз на `hours` годин."""
    last = state.get("notified", {}).get(kind)
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < hours * 3600:
                return False
        except ValueError:
            pass
    state.setdefault("notified", {})[kind] = now.isoformat()
    return True


async def notify(text: str, *, token: str, chat: str, dry_run: bool = False) -> None:
    """Надіслати адміну. Помилки відправки лише друкуємо: сповіщення не мають ламати бота."""
    if dry_run:
        chat = chat or "admin"
    if not chat or not (token or dry_run):
        return
    try:
        async with aiohttp.ClientSession() as session:
            await Telegram(session, token, [chat], dry_run=dry_run).message(text)
    except Exception as err:  # noqa: BLE001
        print(f"Не вдалося написати адміну: {err!r}")
