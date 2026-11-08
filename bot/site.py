"""Сайт для GitHub Pages: одна самодостатня сторінка docs/index.html з поточним графіком.

Сторінка сама рахує «зараз» у браузері (за київським часом), тож показує, є світло чи ні
і коли наступна зміна, навіть якщо бот давно нічого не публікував.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ua_outages.models import DaySchedule, group_sort_key

from . import ics
from .message import WEEKDAYS, date_label, outage_hours

TEMPLATE = Path(__file__).with_name("site_template.html")


def _name(day: date, today: date) -> str:
    if day == today:
        return "Сьогодні"
    if (day - today).days == 1:
        return "Завтра"
    return WEEKDAYS[day.weekday()].capitalize()


def site_data(schedules: dict[date, DaySchedule], now: datetime) -> dict:
    days = sorted(d for d in schedules if d >= now.date())[:2]
    return {
        "updated": f"{now:%d.%m %H:%M}",
        "days": [{
            "date": d.isoformat(),
            "name": _name(d, now.date()),
            "label": date_label(d),
            "full": f"{date_label(d)}, {WEEKDAYS[d.weekday()]}",
            "groups": {g: [[round(a, 4), round(b, 4), int(m)] for a, b, m in outage_hours(schedules[d], g)]
                       for g in sorted(schedules[d].groups, key=group_sort_key)},
        } for d in days],
    }


def render_site(schedules: dict[date, DaySchedule], now: datetime) -> str:
    payload = json.dumps(site_data(schedules, now), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # щоб дані ніколи не закрили тег <script>
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)


def write_site(path: Path, schedules: dict[date, DaySchedule], now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_site(schedules, now), encoding="utf-8")
    ics.write_calendars(path.parent / "cal", schedules, now)
