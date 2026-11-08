"""Календарі .ics, підсумок тижня й нові блоки сайту."""
from datetime import date, datetime, timedelta

import pytest
from ua_outages.models import KYIV

from bot import ics, site, weekly
from bot.demo import sample_schedule
from test_admin import Env, TODAY, at  # noqa: F401  (фікстури й помічники)
from test_admin import env  # noqa: F401

NOW = datetime(2026, 11, 8, 14, 10, tzinfo=KYIV)


def test_ics_events_alarm_and_utc():
    text = ics.build_ics("1.1", {TODAY: sample_schedule(TODAY)}, NOW)
    assert text.startswith("BEGIN:VCALENDAR") and text.rstrip().endswith("END:VCALENDAR")
    assert text.count("BEGIN:VEVENT") == 5 == text.count("END:VEVENT")        # 1.1: п'ять відключень
    assert text.count("TRIGGER:-PT15M") == 5
    assert "DTSTART:20261107T220000Z" in text and "DTEND:20261108T000000Z" in text  # 00:00–02:00 Київ = UTC+2
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))        # RFC: рядки не довші за 75 байтів
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")


def test_ics_only_today_and_tomorrow_and_files(tmp_path):
    scheds = {date(2026, 11, 7): sample_schedule(date(2026, 11, 7)), TODAY: sample_schedule(TODAY)}
    text = ics.build_ics("3.1", scheds, NOW)
    assert "20261107" not in text.split("BEGIN:VEVENT", 1)[1].split("END:VEVENT")[0][:60]  # вчорашніх подій немає
    site.write_site(tmp_path / "docs" / "index.html", scheds, NOW)
    files = sorted(p.name for p in (tmp_path / "docs" / "cal").glob("*.ics"))
    assert files[:3] == ["1-1.ics", "1-2.ics", "2-1.ics"] and len(files) == 12


def test_site_has_calendar_and_share():
    html = site.render_site({TODAY: sample_schedule(TODAY)}, NOW)
    for needle in ("calendarCard", "webcal:", 'data-act="share"', 'get("q")'):
        assert needle in html


def history(days):
    st = {}
    for d in days:
        weekly.update_history(st, {d: sample_schedule(d)}, d)
    return st


def test_weekly_text_ranking_and_minimum_days():
    week = [TODAY - timedelta(days=6 - i) for i in range(7)]
    text = weekly.weekly_text(history(week), TODAY)
    assert "ПІДСУМОК ТИЖНЯ" in text and "2–8 листопада" in text and "🥇" in text and "🥶" in text
    assert text.index("<b>3.2</b>") < text.index("<b>6.2</b>")                # менше годин — вище в рейтингу
    assert weekly.weekly_text(history(week[-2:]), TODAY) is None              # менше трьох днів: не публікуємо
    assert "Дані за 3 дн." in weekly.weekly_text(history(week[-3:]), TODAY)


def test_longest_pause_merges_across_midnight():
    hist = {"2026-11-07": {"1.1": [[20.0, 24.0]]}, "2026-11-08": {"1.1": [[0.0, 3.0]]}}
    length, day, start = weekly._longest_pause([date(2026, 11, 7), TODAY], hist, "1.1")
    assert (length, day, start) == (7.0, date(2026, 11, 7), 20.0)


def test_weekly_published_once_on_sunday_evening(env):
    week = [TODAY - timedelta(days=6 - i) for i in range(7)]
    for d in week[:-1]:
        env.run(hour=12, day=d)
    _, out = env.run(hour=19, day=TODAY)
    assert "ПІДСУМОК ТИЖНЯ" not in out
    _, out = env.run(hour=21, day=TODAY)
    assert "ПІДСУМОК ТИЖНЯ" in out and "підсумок тижня" in out                # і нотатка адміну
    _, out = env.run(hour=22, day=TODAY)
    assert "ПІДСУМОК ТИЖНЯ" not in out
