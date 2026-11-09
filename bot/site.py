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


HISTORY_DAYS = 14


def _history(history: dict | None, today: date) -> dict:
    """Минулі дні для дашборда: {дата: {черга: [[з, до], ...]}}, лише певні відключення."""
    out: dict = {}
    for key in sorted(history or {}):
        try:
            if date.fromisoformat(key) >= today:
                continue
            out[key] = {g: [[round(float(a), 2), round(float(b), 2)] for a, b in spans]
                        for g, spans in history[key].items()}
        except (ValueError, TypeError):
            continue  # зіпсований запис в історії не повинен ламати сайт
    return dict(list(out.items())[-HISTORY_DAYS:])


def site_data(schedules: dict[date, DaySchedule], now: datetime, history: dict | None = None) -> dict:
    days = sorted(d for d in schedules if d >= now.date())[:2]
    return {
        "updated": f"{now:%d.%m %H:%M}",
        "history": _history(history, now.date()),
        "days": [{
            "date": d.isoformat(),
            "name": _name(d, now.date()),
            "label": date_label(d),
            "full": f"{date_label(d)}, {WEEKDAYS[d.weekday()]}",
            "groups": {g: [[round(a, 4), round(b, 4), int(m)] for a, b, m in outage_hours(schedules[d], g)]
                       for g in sorted(schedules[d].groups, key=group_sort_key)},
        } for d in days],
    }


def render_site(schedules: dict[date, DaySchedule], now: datetime, history: dict | None = None) -> str:
    payload = json.dumps(site_data(schedules, now, history), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # щоб дані ніколи не закрили тег <script>
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)


def write_site(path: Path, schedules: dict[date, DaySchedule], now: datetime, history: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_site(schedules, now, history), encoding="utf-8")
    ics.write_calendars(path.parent / "cal", schedules, now)
