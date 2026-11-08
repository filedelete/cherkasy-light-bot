"""Демо без Telegram і без мережі: друкує приклади повідомлень у консоль.

    python -m bot.demo
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from ua_outages.models import KYIV, DaySchedule
from ua_outages.providers.cherkasy import parse_post
from ua_outages.timeline import diff_schedules

from . import message

SAMPLE = Path(__file__).resolve().parent.parent / "tests" / "sample_2026-11-08.json"


def _hhmm(x: float) -> str:
    return f"{int(x):02d}:{round(x % 1 * 60):02d}"


def sample_schedule(day: date = date(2026, 11, 8), tweaks: dict[str, list[tuple[float, float]]] | None = None) -> DaySchedule:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    data.update({g: [tuple(i) for i in iv] for g, iv in (tweaks or {}).items()})
    html = "".join(f"<p>{g} " + ", ".join(f"{_hhmm(a)} - {_hhmm(b)}" for a, b in iv) + "</p>"
                   for g, iv in data.items())
    return parse_post({"data": {"content": html}}, day, datetime(day.year, day.month, day.day, 0, 51, tzinfo=KYIV))


if __name__ == "__main__":
    today = date(2026, 11, 8)
    old = {today: sample_schedule(today)}
    new = {today: sample_schedule(today, {"1.1": [(0, 2), (4, 8), (10, 14)], "3.1": [(7, 10), (12.5, 16)]})}
    print("=== Новий графік ===\n")
    print(message.build(diff_schedules({}, old)[0]))
    print("\n=== Графік змінено ===\n")
    print(message.build(diff_schedules(old, new)[0]))
