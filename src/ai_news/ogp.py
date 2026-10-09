"""The daily share image (OGP, 1200x630 PNG): AI weather, Nyusuke and the top story."""

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ai_news.mascot import MOODS, WEATHER_MOODS
from ai_news.paths import TEMPLATES_DIR
from ai_news.schemas import Edition

WIDTH, HEIGHT = 1200, 630
FONT_PATH = TEMPLATES_DIR / "fonts" / "MPLUSRounded1c-ExtraBold.ttf"
SUPERSAMPLE = 4

BG = "#F3FAF7"
CARD = "#FFFFFF"
LINE = "#D7EAE3"
TEXT = "#1F2D2A"
SUB = "#4F615C"
ACCENT = "#0B7A65"
PALE = "#EAF7F2"
GOLD = "#FFB547"
GOLD_TEXT = "#3D2600"

WEATHER_TEXT = {"thunder": "かみなり・大ニュースの日", "cloudy": "くもり・ちょっと動きあり", "sunny": "はれ・おだやかな一日"}
NO_LINE_START = set("、。，．・：；？！ー」』）】〉》")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


# Nyusuke, drawn from the same shapes as the SVG (viewBox 0 0 160 170).


def _path_points(d: str, steps: int = 20) -> tuple[list[tuple[float, float]], bool]:
    """Points along a path made of M, L, Q and Z commands."""
    tokens = re.findall(r"[MLQZ]|-?\d+(?:\.\d+)?", d)
    points: list[tuple[float, float]] = []
    closed = False
    i = 0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd in ("M", "L"):
            points.append((float(tokens[i + 1]), float(tokens[i + 2])))
            i += 3
        elif cmd == "Q":
            (x0, y0), cx, cy, x1, y1 = points[-1], *map(float, tokens[i + 1 : i + 5])
            for n in range(1, steps + 1):
                t = n / steps
                points.append(
                    ((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
                     (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
                )  # fmt: skip
            i += 5
        elif cmd == "Z":
            closed = True
            i += 1
        else:
            raise ValueError(f"unsupported path token {cmd!r}")
    return points, closed


def draw_mascot(mood: str, width: int) -> Image.Image:
    """Nyusuke as an RGBA image `width` pixels wide."""
    m = MOODS[mood]
    s = width * SUPERSAMPLE / 160
    img = Image.new("RGBA", (round(160 * s), round(170 * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(cx, cy, rx, ry):
        return [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]

    def rect(x, y, w, h):
        return [x * s, y * s, (x + w) * s, (y + h) * s]

    def stroke(points, color, w):
        scaled = [(x * s, y * s) for x, y in points]
        d.line(scaled, fill=color, width=round(w * s), joint="curve")
        for x, y in (scaled[0], scaled[-1]):  # round caps
            r = w * s / 2
            d.ellipse([x - r, y - r, x + r, y + r], fill=color)

    lw = round(3 * s)
    d.ellipse(box(80, 162, 40, 6), fill=(31, 45, 42, 26))
    d.line([(80 * s, 34 * s), (80 * s, 18 * s)], fill=TEXT, width=lw)
    d.ellipse(box(80, 14, 7, 7), fill=GOLD, outline=TEXT, width=lw)
    for cx in (60, 100):
        d.ellipse(box(cx, 146, 14, 8), fill="#5FC4AB", outline=TEXT, width=lw)
    for x in (14, 126):
        d.rounded_rectangle(rect(x, 86, 20, 34), radius=10 * s, fill="#7FD9C2", outline=TEXT, width=lw)
    d.rounded_rectangle(rect(26, 32, 108, 112), radius=50 * s, fill="#7FD9C2", outline=TEXT, width=lw)
    d.rounded_rectangle(rect(42, 50, 76, 50), radius=22 * s, fill=TEXT)
    if m["arcs"]:
        for eye in ("M57 77 Q64 68 71 77", "M89 77 Q96 68 103 77"):
            stroke(_path_points(eye)[0], "#FFFFFF", 4)
    else:
        for cx in (m["lx"], m["rx"]):
            d.ellipse(box(cx, m["ey"], m["r"], m["r"]), fill="#FFFFFF")
    mouth, closed = _path_points(m["mouth"])
    if closed:
        d.polygon([(x * s, y * s) for x, y in mouth], fill="#FFFFFF")
    stroke(mouth + ([mouth[0]] if closed else []), "#FFFFFF", 3.5)
    for cx in (44, 116):
        d.ellipse(box(cx, 112, 6, 6), fill=(255, 143, 168, 166))
    d.rounded_rectangle(rect(66, 110, 28, 16), radius=6 * s, fill="#FFFFFF", outline=TEXT, width=round(2 * s))
    beat = [(69, 118), (74, 118), (77, 113), (81, 123), (84, 117), (91, 117)]
    stroke(beat, ACCENT, 2)
    return img.resize((width, round(width * 170 / 160)), Image.Resampling.LANCZOS)


# Text


WRAP_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*|\s+|.")


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    """Break Japanese text between characters, but never inside a Latin word or number,
    and never put closing punctuation at the start of a line."""
    lines: list[str] = []
    current = ""
    for token in WRAP_TOKEN.findall(text):
        fits = font.getlength(current + token) <= max_width
        if current and not fits and token[0] not in NO_LINE_START:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current += token
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.getlength(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, font, fill: str, color: str) -> int:
    """Draw a rounded label; returns its right edge."""
    w = round(font.getlength(text))
    h = font.size + 22
    d.rounded_rectangle([x, y, x + w + 40, y + h], radius=h // 2, fill=fill)
    d.text((x + 20, y + h / 2), text, font=font, fill=color, anchor="lm")
    return x + w + 40


def render_ogp(edition: Edition, path: Path) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([36, 36, WIDTH - 36, HEIGHT - 36], radius=44, fill=CARD, outline=LINE, width=3)

    # Left: Nyusuke with today's face, on a mint disc.
    d.ellipse([86, 150, 406, 470], fill=PALE)
    mascot = draw_mascot(WEATHER_MOODS[edition.weather], 270)
    img.paste(mascot, (111, 160), mascot)

    # Right: brand, date, weather, top story.
    x = 450
    right = WIDTH - 84
    d.text((x, 84), "おはようAI", font=_font(52), fill=TEXT)
    d.text((x + 300, 104), f"{edition.date.month}月{edition.date.day}日の朝", font=_font(30), fill=SUB)
    _pill(d, x, 170, f"今日のAI天気 {WEATHER_TEXT[edition.weather]}", _font(28), PALE, ACCENT)

    if edition.articles:
        top = edition.articles[0]
        label = "今日いちばん" if top.score == 5 else "今日のトップ"
        _pill(d, x, 252, label, _font(26), GOLD, GOLD_TEXT)
        title_font = _font(46)
        for n, line in enumerate(wrap(top.title_ja, title_font, right - x, 3)):
            d.text((x, 322 + n * 66), line, font=title_font, fill=TEXT)

    d.text((x, HEIGHT - 96), "AIが毎朝まとめる、やさしいAIニュース", font=_font(26), fill=SUB)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
