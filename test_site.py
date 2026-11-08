"""Сайт для GitHub Pages: дані в сторінці й безпека вбудовування."""
import json
import re
from datetime import date, datetime

from ua_outages.models import KYIV

from bot import site
from bot.demo import sample_schedule

NOW = datetime(2026, 11, 8, 14, 10, tzinfo=KYIV)


def schedules():
    return {date(2026, 11, 7): sample_schedule(date(2026, 11, 7)),  # вчора: має відсіятись
            date(2026, 11, 8): sample_schedule(), date(2026, 11, 9): sample_schedule(date(2026, 11, 9))}


def test_site_data_has_today_and_tomorrow_only():
    data = site.site_data(schedules(), NOW)
    assert [d["date"] for d in data["days"]] == ["2026-11-08", "2026-11-09"]
    assert [d["name"] for d in data["days"]] == ["Сьогодні", "Завтра"]
    g = data["days"][0]["groups"]
    assert list(g)[:3] == ["1.1", "1.2", "2.1"] and g["1.1"][0] == [0.0, 2.0, 0]


def test_site_html_embeds_valid_json():
    html = site.render_site(schedules(), NOW)
    assert "__DATA__" not in html
    payload = re.search(r"const D = (\{.*?\});\n", html, re.S).group(1)
    assert json.loads(payload)["updated"] == "08.11 14:10"


def test_site_data_cannot_close_script_tag(monkeypatch):
    monkeypatch.setattr(site, "_name", lambda d, t: "</script><b>x")
    html = site.render_site(schedules(), NOW)
    assert html.count("</script>") == 1  # лише власний закриваючий тег сторінки
