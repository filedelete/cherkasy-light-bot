"""Підсумок тижня за графіком: рейтинг черг, найдовша пауза без світла, середнє.

Історія — це графіки днів, що вже минули (зберігаються в state, останні 3 тижні).
Рахуємо за графіком: аварійні відключення сюди не потрапляють.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

from ua_outages.models import DaySchedule, group_sort_key

from .message import LINE, MONTHS, hours_text, outage_hours

KEEP_DAYS = 21
MIN_DAYS = 3   # менше днів даних: підсумок не публікуємо
MEDALS = ["🥇", "🥈", "🥉"]


def update_history(state: dict, schedules: dict[date, DaySchedule], today: date) -> None:
    """Запам'ятовує останній відомий графік кожного дня (перезаписується, поки день не минув)."""
    hist = state.setdefault("history", {})
    for day, sched in schedules.items():
        hist[day.isoformat()] = {g: [[round(a, 4), round(b, 4)] for a, b, maybe in outage_hours(sched, g) if not maybe]
                                 for g in sched.groups}
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k in hist if k < cutoff]:
        del hist[k]


def week_of(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def _longest_pause(days: list[date], hist: dict, group: str) -> tuple[float, date, float]:
    """Найдовше відключення поспіль, зі склейкою через північ: (годин, день початку, година початку)."""
    spans = []
    for i, d in enumerate(days):
        for a, b in hist.get(d.isoformat(), {}).get(group, []):
            spans.append([i * 24 + a, i * 24 + b])
    spans.sort()
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if not merged:
        return 0.0, days[0], 0.0
    a, b = max(merged, key=lambda x: x[1] - x[0])
    return b - a, days[int(a // 24)], a % 24


def _clock(x: float) -> str:
    h, m = int(x), round((x - int(x)) * 60)
    return f"{h:02d}:{m:02d}" if m < 60 else f"{h + 1:02d}:00"


def weekly_text(state: dict, today: date) -> str | None:
    monday, sunday = week_of(today)
    hist = state.get("history", {})
    days = [monday + timedelta(days=i) for i in range(7) if monday + timedelta(days=i) <= today]
    days = [d for d in days if d.isoformat() in hist]
    if len(days) < MIN_DAYS:
        return None
    groups = sorted({g for d in days for g in hist[d.isoformat()]}, key=group_sort_key)
    totals = {g: sum(b - a for d in days for a, b in hist[d.isoformat()].get(g, [])) for g in groups}
    ranking = sorted(groups, key=lambda g: (totals[g], group_sort_key(g)))
    top = max(totals.values()) or 1
    longest = max(((_longest_pause(days, hist, g), g) for g in groups), key=lambda x: x[0][0])
    (length, day0, h0), lg = longest
    avg = sum(totals.values()) / len(groups) / len(days)

    rows = []
    for i, g in enumerate(ranking):
        icon = MEDALS[i] if i < len(MEDALS) else ("🥶" if i == len(ranking) - 1 else "▪️")
        filled = round(8 * totals[g] / top)
        rows.append(f"{icon} <b>{escape(g)}</b>  {'▰' * filled}{'▱' * (8 - filled)}  {hours_text(totals[g])}")

    period = (f"{monday.day}–{sunday.day} {MONTHS[sunday.month - 1]}" if monday.month == sunday.month
              else f"{monday.day} {MONTHS[monday.month - 1]} – {sunday.day} {MONTHS[sunday.month - 1]}")
    lines = [f"📊 <b>ПІДСУМОК ТИЖНЯ</b>\n{LINE}\n🗓 {period} · за графіком"]
    if len(days) < 7:
        lines[0] += f"\n<i>Дані за {len(days)} дн. з 7</i>"
    lines.append(f"🕐 У середньому по області: <b>{hours_text(avg)}</b> на добу\n"
                 f"🌑 Найдовше без світла поспіль: <b>{hours_text(length)}</b>, "
                 f"черга {escape(lg)} (з {_clock(h0)}, {day0.day} {MONTHS[day0.month - 1]})")
    lines.append("<b>Рейтинг черг</b> <i>(менше годин = краще)</i>\n" + "\n".join(rows))
    lines.append("<i>Рахується за графіком Черкасиобленерго, аварійні відключення не враховано.</i>")
    return "\n\n".join(lines)
