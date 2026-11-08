"""Календар відключень для кожної черги (.ics): підписка в Google/Apple/Outlook календарі.

Подія = відключення, за 15 хвилин до нього календар нагадує. У файлі лише сьогодні
й завтра, тож при оновленні графіка календар підтягує свіжі дані (зазвичай раз на кілька годин).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ua_outages.models import KYIV, DaySchedule, group_sort_key

from .message import date_label, outage_hours

ALARM_MINUTES = 15


def slug(group: str) -> str:
    return group.replace(".", "-")


def _utc(day: date, hours: float) -> str:
    local = datetime.combine(day, time(0), tzinfo=KYIV) + timedelta(hours=hours)
    return local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(text: str) -> str:
    bs = chr(92)  # зворотна скісна риска: RFC 5545 екранує \, ; , і переноси рядка
    return (text.replace(bs, bs + bs).replace(";", bs + ";").replace(",", bs + ",").replace("\n", bs + "n"))


def build_ics(group: str, schedules: dict[date, DaySchedule], now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cherkasy-light-bot//UK",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_esc(f'Світло · черга {group}')}", "X-WR-TIMEZONE:Europe/Kyiv",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for day in sorted(d for d in schedules if d >= now.date())[:2]:
        for a, b, maybe in outage_hours(schedules[day], group):
            lines += ["BEGIN:VEVENT",
                      f"UID:{slug(group)}-{day.isoformat()}-{int(a * 60)}@cherkasy-light-bot",
                      f"DTSTAMP:{stamp}", f"DTSTART:{_utc(day, a)}", f"DTEND:{_utc(day, b)}",
                      f"SUMMARY:{'🟡 Можливо без світла' if maybe else '🔴 Без світла'} · {group}",
                      f"DESCRIPTION:{_esc(f'Черга {group}, {date_label(day)}. За графіком Черкасиобленерго.')}",
                      "STATUS:TENTATIVE" if maybe else "STATUS:CONFIRMED", "TRANSP:TRANSPARENT",
                      "BEGIN:VALARM", "ACTION:DISPLAY",
                      f"DESCRIPTION:{_esc(f'Через {ALARM_MINUTES} хв відключення світла ({group})')}",
                      f"TRIGGER:-PT{ALARM_MINUTES}M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _fold(line: str) -> str:
    """RFC 5545: рядки довші за 75 байтів переносяться (кирилиця й емодзі займають кілька байтів)."""
    raw, out, cur = line, [], ""
    for ch in raw:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def write_calendars(folder: Path, schedules: dict[date, DaySchedule], now: datetime) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    groups = {g for d, s in schedules.items() if d >= now.date() for g in s.groups}
    for g in sorted(groups, key=group_sort_key):
        (folder / f"{slug(g)}.ics").write_text(build_ics(g, schedules, now), encoding="utf-8", newline="")
