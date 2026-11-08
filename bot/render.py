"""Картинка графіка: усі черги на добу, мобільний формат (800 px завширшки, ×2 для різкості)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from ua_outages.models import DaySchedule, group_sort_key

S = 2  # суперсемплінг: малюємо вдвічі більше й стискаємо, щоб краї були гладкі
FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "Manrope.ttf"

BG = (14, 20, 32)
PANEL = (22, 31, 47)
GRID = (41, 54, 78)
TEXT = (234, 240, 250)
MUTED = (138, 151, 176)
ON = (43, 174, 116)
OFF = (232, 72, 79)
MAYBE = (242, 179, 61)
AMBER = (242, 179, 61)
DARK = (28, 22, 8)

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
          "серпня", "вересня", "жовтня", "листопада", "грудня"]
WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]


def date_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def hours_text(hours: float) -> str:
    value = f"{hours:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{value} год"


@lru_cache(maxsize=None)
def font(size: int, weight: int = 500) -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(str(FONT_PATH), size * S)
        f.set_variation_by_axes([weight])
        return f
    except Exception:  # немає шрифту в репозиторії: запасний варіант
        return ImageFont.load_default(size * S)


def outage_hours(sched: DaySchedule, group: str, *, possible: bool = False) -> list[tuple[float, float, bool]]:
    """Відключення черги як (початок, кінець, можливе) у годинах від півночі цього дня."""
    start_of_day = datetime.combine(sched.day, time(0), tzinfo=None)
    result = []
    for o in sched.outages(group):
        a = (o.start.replace(tzinfo=None) - start_of_day).total_seconds() / 3600
        b = (o.end.replace(tzinfo=None) - start_of_day).total_seconds() / 3600
        a, b = max(0.0, a), min(24.0, b)
        if b > a:
            result.append((a, b, bool(o.possible)))
    return result


def total_off(sched: DaySchedule, group: str) -> float:
    return sum(b - a for a, b, maybe in outage_hours(sched, group) if not maybe)


def currently_off(sched: DaySchedule, now: datetime) -> list[str]:
    hour = now.hour + now.minute / 60
    return [g for g in sorted(sched.groups, key=group_sort_key)
            if any(a <= hour < b and not maybe for a, b, maybe in outage_hours(sched, g))]


class Canvas:
    """Малювання в логічних пікселях (1×); усередині множимо на S."""

    def __init__(self, w: int, h: int):
        self.img = Image.new("RGBA", (w * S, h * S), BG + (255,))
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x0, y0, x1, y1, fill, r=0, outline=None, width=1):
        self.d.rounded_rectangle((x0 * S, y0 * S, x1 * S, y1 * S), radius=r * S, fill=fill,
                                 outline=outline, width=width * S)

    def line(self, x0, y0, x1, y1, fill, width=1):
        self.d.line((x0 * S, y0 * S, x1 * S, y1 * S), fill=fill, width=int(width * S))

    def text(self, xy, s, size, fill=TEXT, weight=500, anchor="ls"):
        self.d.text((xy[0] * S, xy[1] * S), s, font=font(size, weight), fill=fill, anchor=anchor)

    def width(self, s, size, weight=500) -> float:
        return font(size, weight).getlength(s) / S

    def polygon(self, pts, fill):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill)

    def ellipse(self, cx, cy, r, fill):
        self.d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), fill=fill)

    def shade(self, x0, y0, x1, y1, alpha):
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle((x0 * S, y0 * S, x1 * S, y1 * S), fill=PANEL + (alpha,))
        self.img = Image.alpha_composite(self.img, layer)
        self.d = ImageDraw.Draw(self.img)


def render(sched: DaySchedule, now: datetime, path: str | Path, *, changed=(), badge: str | None = None) -> Path:
    groups = sorted(sched.groups, key=group_sort_key)
    is_today = now.date() == sched.day
    changed = set(changed)
    any_maybe = any(maybe for g in groups for *_, maybe in outage_hours(sched, g))

    W, M = 800, 32
    PAD = 24
    x0, x1 = 118, W - M - PAD - 72
    per_hour = (x1 - x0) / 24
    bar_h, pitch, group_gap = 30, 40, 14
    axis_h = 46

    rows, y = {}, 0
    prev = None
    for g in groups:
        if prev is not None and g.split(".")[0] != prev.split(".")[0]:
            y += group_gap
        rows[g] = y
        y += pitch
        prev = g
    rows_h = y

    header_h = 148
    panel_top = header_h
    panel_h = PAD + axis_h + rows_h + (50 if is_today else PAD)
    footer_h = 126 if is_today else 92
    H = panel_top + panel_h + footer_h
    c = Canvas(W, H)

    # --- шапка
    c.rect(M, 40, M + 56, 96, AMBER, r=16)
    c.polygon([(M + 31, 49), (M + 18, 71), (M + 27, 71), (M + 24, 88), (M + 39, 64), (M + 30, 64)], DARK)
    c.text((M + 76, 70), "Черкаська область", 36, TEXT, 800)
    c.text((M + 76, 98), f"Відключення на {date_label(sched.day)}, {WEEKDAYS[sched.day.weekday()]}", 19, MUTED, 600)

    label = badge or (f"Оновлено о {sched.updated_at:%H:%M}" if sched.updated_at else None)
    if label:
        w = c.width(label, 16, 700) + 32
        if badge:
            c.rect(W - M - w, 112, W - M, 144, AMBER, r=16)
            c.text((W - M - w / 2, 128), label, 16, DARK, 800, "mm")
        else:
            c.rect(W - M - w, 112, W - M, 144, PANEL, r=16)
            c.text((W - M - w / 2, 128), label, 16, MUTED, 700, "mm")

    # --- панель
    c.rect(M, panel_top, W - M, panel_top + panel_h, PANEL, r=24)
    axis_y = panel_top + PAD + 22
    rows_top = panel_top + PAD + axis_h
    rows_bottom = rows_top + rows_h

    for h in range(0, 25, 3):
        x = x0 + h * per_hour
        c.line(x, axis_y + 14, x, rows_bottom, GRID, 1)
        anchor = "ls" if h == 0 else ("rs" if h == 24 else "ms")
        c.text((x, axis_y), f"{h:02d}", 16, MUTED, 600, anchor)

    for g in groups:
        ry = rows_top + rows[g]
        is_changed = g in changed
        c.text((M + PAD + 16, ry + bar_h / 2 + 1), g, 24, AMBER if is_changed else TEXT, 800, "lm")
        if is_changed:
            c.ellipse(M + PAD + 5, ry + bar_h / 2, 4.5, AMBER)
        c.rect(x0, ry, x1, ry + bar_h, ON, r=9)
        for a, b, maybe in outage_hours(sched, g):
            c.rect(x0 + a * per_hour + 1.5, ry, x0 + b * per_hour - 1.5, ry + bar_h, MAYBE if maybe else OFF, r=9)
        total = total_off(sched, g)
        c.text((W - M - PAD, ry + bar_h / 2 + 1), hours_text(total) if total else "—", 17, MUTED, 700, "rm")

    # --- «зараз»
    if is_today:
        xn = x0 + (now.hour + now.minute / 60) * per_hour
        c.shade(x0 - 4, rows_top - 6, xn, rows_bottom + 4, 120)
        c.line(xn, rows_top - 8, xn, rows_bottom + 6, TEXT, 2.5)
        label = f"{now:%H:%M}"
        pw = c.width(label, 16, 800) + 24
        py = rows_bottom + 12
        c.rect(xn - pw / 2, py, xn + pw / 2, py + 28, TEXT, r=14)
        c.text((xn, py + 14), label, 16, BG, 800, "mm")

    # --- підвал
    fy = panel_top + panel_h + 36
    if is_today:
        off = currently_off(sched, now)
        status = ("Зараз без світла: " + ", ".join(off)) if off else "Зараз світло є в усіх чергах"
        c.text((M, fy), status[:70], 20, TEXT, 700)
        fy += 40
    lx = M
    items = [(ON, "Світло є"), (OFF, "Відключення")]
    if any_maybe:
        items.append((MAYBE, "Можливо"))
    for color, name in items:
        c.rect(lx, fy - 14, lx + 18, fy + 4, color, r=5)
        c.text((lx + 28, fy - 5), name, 17, MUTED, 600, "lm")
        lx += 28 + c.width(name, 17, 600) + 28
    if changed:
        c.ellipse(lx + 6, fy - 5, 5, AMBER)
        c.text((lx + 20, fy - 5), "Черга змінилась", 17, MUTED, 600, "lm")
    c.text((W - M, fy + 34), "Джерело: Черкасиобленерго", 15, MUTED, 500, "rs")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    c.img.convert("RGB").save(out, optimize=True)
    return out
