"""Наскрізний тест без мережі: підміняємо джерело й Telegram (DRY_RUN)."""
import asyncio
from datetime import date, datetime

from ua_outages.models import KYIV

from bot import main as bot_main
from bot.demo import sample_schedule


def run(monkeypatch, tmp_path, schedules):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(bot_main, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(bot_main, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(bot_main, "SITE_PATH", tmp_path / "docs" / "index.html")

    async def fake(_now):
        return schedules

    monkeypatch.setattr(bot_main, "fetch_schedules", fake)
    monkeypatch.setattr(bot_main, "now_kyiv", lambda: datetime(2026, 11, 8, 12, 0, tzinfo=KYIV))  # день демо-графіка
    assert asyncio.run(bot_main.run()) == 0


def messages(tmp_path):
    return sorted((tmp_path / "out").glob("message_*.html"))


def test_publish_then_update_then_quiet(monkeypatch, tmp_path, capsys):
    today = date(2026, 11, 8)
    v1 = {today: sample_schedule(today)}
    run(monkeypatch, tmp_path, v1)
    out = capsys.readouterr().out
    assert "Опубліковано новий графік" in out and "8 листопада" in out
    page = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "__DATA__" not in page and '"2026-11-08"' in page  # сайт для GitHub Pages створено

    run(monkeypatch, tmp_path, v1)  # без змін
    assert "змін 0" in capsys.readouterr().out

    v2 = {today: sample_schedule(today, {"1.1": [(0, 2), (4, 8), (10, 14)]})}  # 1.1 змінили
    run(monkeypatch, tmp_path, v2)
    out = capsys.readouterr().out
    assert "Графік оновлено" in out and "<b>1.1</b>" in out and "➖" in out and "➕" in out
    assert "Що змінилось" in out and "🔄" in out
