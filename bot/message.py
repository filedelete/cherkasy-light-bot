"""Тексти повідомлень (Telegram HTML).

Одне повідомлення = один день. Зверху: що сталось і скільки це годин без світла,
далі (якщо графік змінився) що саме змінилось, і нижче повний графік по чергах.
"""
from __future__ import annotations

from datetime import date, datetime, time
from html import escape

from ua_outages.models import DaySchedule, group_sort_key
from ua_outages.timeline import DayChange

MAX_DIFF_ROWS = 8
DIVIDER = "━━━━━━━━━━━━━━"

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
          "серпня", "вересня", "жовтня", "листопада", "грудня"]
WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]


# ---------- час і тривалість ----------

def date_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def hours_text(hours: float) -> str:
    value = f"{hours:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{value} год"


def _clock(x: float) -> str:
    """6.0 → «06», 6.5 → «06:30», 24.0 → «24»."""
    h, m = int(x), round((x - int(x)) * 60)
    if m == 60:
        h, m = h + 1, 0
    return f"{h:02d}" if m == 0 else f"{h:02d}:{m:02d}"


def _span(a: float, b: float) -> str:
    return f"{_clock(a)}–{_clock(b)}"


def outage_hours(sched: DaySchedule, group: str) -> list[tuple[float, float, bool]]:
    """Відключення черги як (початок, кінець, можливе) у годинах від півночі цього дня."""
    start_of_day = datetime.combine(sched.day, time(0), tzinfo=None)
    result = []
    for o in sched.outages(group):
        a = (o.start.replace(tzinfo=None) - start_of_day).total_seconds() / 3600
        b = (o.end.replace(tzinfo=None) - start_of_day).total_seconds() / 3600
        a, b = max(0.0, a), min(24.0, b)
        if b > a:
            result.append((a, b, bool(o.possible)))
    return sorted(result)


def total_off(sched: DaySchedule, group: str) -> float:
    return sum(b - a for a, b, maybe in outage_hours(sched, group) if not maybe)


def no_outages(sched: DaySchedule) -> bool:
    return bool(sched.groups) and all(not o for o in sched.groups.values())


# ---------- блоки повідомлення ----------

def summary(sched: DaySchedule) -> str:
    totals = {g: total_off(sched, g) for g in sched.groups}
    if not totals or max(totals.values()) == 0:
        return "Відключень за графіком немає."
    lo, hi = min(totals.values()), max(totals.values())
    if lo == hi:
        return f"🕐 Без світла за графіком: <b>{hours_text(hi)}</b> на добу"
    best = [g for g, t in totals.items() if t == lo]
    worst = [g for g, t in totals.items() if t == hi]

    def names(gs):
        gs = sorted(gs, key=group_sort_key)
        return ", ".join(gs[:4]) + ("…" if len(gs) > 4 else "")

    return (f"🕐 Без світла за графіком: <b>від {hours_text(lo)[:-4]} до {hours_text(hi)}</b> на добу\n"
            f"😎 Найлегше: <b>{names(best)}</b> ({hours_text(lo)})\n"
            f"🥶 Найважче: <b>{names(worst)}</b> ({hours_text(hi)})")


def queue_block(sched: DaySchedule, group: str, *, changed: bool = False) -> str:
    """Дві стрічки: «1.1 · 10 год» і години відключень."""
    mark = " 🔄" if changed else ""
    spans = outage_hours(sched, group)
    sure = [_span(a, b) for a, b, maybe in spans if not maybe]
    maybe = [_span(a, b) for a, b, maybe in spans if maybe]
    total = total_off(sched, group)
    head = f"<b>{escape(group)}</b>{mark}  ·  " + (hours_text(total) if total else "без відключень")
    if not spans:
        return f"{head}\n🟢 світло є весь день"
    lines = [head]
    if sure:
        lines.append("🔴 " + " · ".join(sure))
    if maybe:
        lines.append("🟡 можливо: " + " · ".join(maybe))
    return "\n".join(lines)


def schedule_text(sched: DaySchedule, changed=()) -> str:
    """Повний графік: черги парами (1.1 і 1.2 разом), між парами порожній рядок."""
    changed = set(changed)
    blocks, prev = [], None
    for g in sorted(sched.groups, key=group_sort_key):
        block = queue_block(sched, g, changed=g in changed)
        if prev is not None and g.split(".")[0] == prev.split(".")[0]:
            blocks[-1] += "\n" + block
        else:
            blocks.append(block)
        prev = g
    return "\n\n".join(blocks)


def legend(sched: DaySchedule) -> str:
    any_maybe = any(m for g in sched.groups for *_, m in outage_hours(sched, g))
    text = "🔴 світла немає  ·  в решту годин 🟢 світло є"
    return text + ("\n🟡 можливе відключення" if any_maybe else "")


def diff_lines(change: DayChange) -> list[str]:
    lines = []
    for g in sorted(change.groups, key=group_sort_key):
        old = {(a, b) for a, b, _ in outage_hours(change.previous, g)} if change.previous else set()
        new = {(a, b) for a, b, _ in outage_hours(change.schedule, g)}
        removed, added = old - new, new - old
        parts = []
        if removed:
            parts.append("➖ " + ", ".join(_span(a, b) for a, b in sorted(removed)))
        if added:
            parts.append("➕ " + ", ".join(_span(a, b) for a, b in sorted(added)))
        if parts:
            lines.append(f"<b>{escape(g)}</b>   " + "    ".join(parts))
    return lines


def _title(sched: DaySchedule) -> str:
    return (f"⚡ <b>ГРАФІК ВІДКЛЮЧЕНЬ</b> ⚡\n"
            f"📍 Черкаська область\n"
            f"🗓 <b>{date_label(sched.day)}</b> · {WEEKDAYS[sched.day.weekday()]}")


def _footer(sched: DaySchedule) -> str:
    upd = f" · оновлено о {sched.updated_at:%H:%M}" if sched.updated_at else ""
    return f"<i>Джерело: Черкасиобленерго{upd}</i>"


def build(change: DayChange) -> str:
    """Готове повідомлення (Telegram HTML) для нового або зміненого графіка."""
    sched = change.schedule
    notes = "".join(f"\n⚠️ {escape(n)}" for n in sched.notes)
    parts = [_title(sched)]

    if change.published:
        parts.append(f"🆕 <b>Опубліковано новий графік</b>{notes}\n\n{summary(sched)}")
    else:
        names = ", ".join(sorted(change.groups, key=group_sort_key))
        parts.append(f"🔄 <b>Графік оновлено</b>\nЗмінились черги: <b>{escape(names)}</b>{notes}")
        rows = diff_lines(change)
        if rows:
            shown = rows[:MAX_DIFF_ROWS]
            if len(rows) > MAX_DIFF_ROWS:
                shown.append(f"…і ще {len(rows) - MAX_DIFF_ROWS}")
            parts.append("<b>Що змінилось</b>\n" + "\n".join(shown))
        parts.append(summary(sched))

    parts.append(DIVIDER + "\n" + legend(sched))
    parts.append(schedule_text(sched, changed=() if change.published else change.groups))
    parts.append(_footer(sched))
    return "\n\n".join(parts)


def all_clear(sched: DaySchedule) -> str:
    return (f"{_title(sched)}\n\n"
            f"✅ <b>Відключень за графіком немає</b>\n"
            f"Світло має бути весь день у всіх чергах.\n\n{_footer(sched)}")
