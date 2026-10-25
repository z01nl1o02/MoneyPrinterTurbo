"""PIL 花字/字幕渲染（全部预烘焙 PNG，MoviePy 端只做定位与弹入缩放）。

提供：大花字(可倾斜/多行)、系列印章、信息条、游戏计数器、对比条、词级大字幕卡。
"""
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

_font_cache = {}


def fnt(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(
            str(config.FONT_BOLD if bold else config.FONT_REG), size, index=0)
    return _font_cache[key]


def _measure(font) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(Image.new("RGBA", (10, 10)))


def text_stamp(lines, size, fill, stroke, tilt=0.0, spacing=10, stroke_w=8) -> Image.Image:
    """大花字：白边/黑边描边，可多行、可倾斜（倾斜直接烘进 PNG）。"""
    font = fnt(size)
    d = _measure(font)
    ws = []
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font, stroke_width=stroke_w)
        ws.append(bb[2] - bb[0])
    hh = d.textbbox((0, 0), lines[0], font=font, stroke_width=stroke_w)[3]
    pad = stroke_w + 14
    w = max(ws) + pad * 2
    h = hh * len(lines) + spacing * (len(lines) - 1) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    y = pad
    for ln, lw in zip(lines, ws):
        dd.text(((w - lw) // 2, y), ln, font=font, fill=fill,
                stroke_width=stroke_w, stroke_fill=stroke)
        y += hh + spacing
    if tilt:
        img = img.rotate(tilt, expand=True, resample=Image.BICUBIC)
    return img


def badge(text) -> Image.Image:
    """右上角系列印章：白底黑字圆角条，微倾斜。"""
    font = fnt(40)
    bb = _measure(font).textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    img = Image.new("RGBA", (w + 52, h + 28), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], 16, fill=(255, 255, 255, 235))
    d.text((26, 12), text, font=font, fill=config.BLACK)
    return img.rotate(-4, expand=True, resample=Image.BICUBIC)


def bar(text, fg=config.WHITE, bg=(0, 0, 0, 165), size=42, accent=None) -> Image.Image:
    """底部/中部信息条（accent 为左侧色条）。"""
    font = fnt(size)
    bb = _measure(font).textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    img = Image.new("RGBA", (w + 56, h + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], 14, fill=bg)
    if accent:
        d.rounded_rectangle([0, 0, 14, img.height - 1], 7, fill=accent)
    d.text((28 + (14 if accent else 0), 13), text, font=font, fill=fg)
    return img


def counter(text, big=False) -> Image.Image:
    """游戏风计数器/比分牌：红底黄框，微倾斜。"""
    size = 96 if big else 76
    font = fnt(size)
    bb = _measure(font).textbbox((0, 0), text, font=font, stroke_width=6)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    img = Image.new("RGBA", (w + 80, h + 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], 20,
                        fill=(180, 20, 20, 235), outline=config.YELLOW, width=5)
    d.text(((img.width - w) // 2, 22), text, font=font, fill=config.WHITE,
           stroke_width=6, stroke_fill=(40, 0, 0, 255))
    return img.rotate(-3, expand=True, resample=Image.BICUBIC)


def vs_bar(left, right, l_ratio=40, r_ratio=301) -> Image.Image:
    """我方 vs 敌方 对比条（长度按数值比例绘制，比例由参数给定）。"""
    img = Image.new("RGBA", (860, 210), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 859, 209], 24, fill=(0, 0, 0, 175))
    f1 = fnt(44)
    d.text((50, 22), left, font=f1, fill=(140, 210, 255, 255))
    d.text((50, 108), right, font=f1, fill=config.RED)
    d.rounded_rectangle([50, 78, 50 + int(760 * l_ratio / r_ratio), 92], 7,
                        fill=(140, 210, 255, 255))
    d.rounded_rectangle([50, 164, 50 + 760, 178], 7, fill=(70, 20, 20, 255))
    return img


# ---------------------------------------------------------------- 词级大字幕
def _word_color(t: str):
    if any(c.isdigit() for c in t):
        return config.YELLOW
    for k in config.RED_WORDS:
        if k in t:
            return config.RED
    return config.WHITE


def subtitle_card(words) -> Image.Image:
    """词级字幕卡：数字黄、关键词红、白字黑边，最多两行。"""
    font = fnt(config.SUB_FONT)
    sw = config.SUB_STROKE
    d = _measure(font)

    def wlen(t):
        return d.textbbox((0, 0), t, font=font, stroke_width=sw)[2]

    text = "".join(t for _, _, t in words)
    if wlen(text) <= config.SUB_MAXW:
        lines = [[(t, _word_color(t)) for _, _, t in words]]
        n = 1
    else:
        target, best, acc, cur = len(text) // 2, (0, -1), 0, []
        for idx, (_, _, t) in enumerate(words):
            cur.append(idx); acc += len(t)
            if abs(acc - target) < abs(best[0] - target):
                best = (acc, idx)
        cut = best[1] + 1
        lines = [[(t, _word_color(t)) for _, _, t in words[:cut]],
                 [(t, _word_color(t)) for _, _, t in words[cut:]]]
        n = 2
    maxw = max(sum(wlen(t) for t, _ in ln) for ln in lines)
    img = Image.new("RGBA", (maxw + 40, config.SUB_LINE_HEIGHT * n + 24), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        x = (img.width - sum(wlen(t) for t, _ in ln)) // 2
        y = 12 + i * config.SUB_LINE_HEIGHT
        for t, c in ln:
            dd.text((x, y), t, font=font, fill=c, stroke_width=sw,
                    stroke_fill=config.BLACK_STROKE)
            x += wlen(t)
    return img


def subtitle_overlays(scene: dict, ovl_dir) -> list:
    """场景词级 cues → 字幕卡 PNG + 时间轴 [{png,start,end,w,h}]。"""
    ovl_dir = Path(ovl_dir)
    ovl_dir.mkdir(parents=True, exist_ok=True)
    units, cur = [], []
    for w in scene["words"]:
        cur.append(w)
        txt = "".join(x[2] for x in cur)
        end_punct = cur[-1][2] and cur[-1][2][-1] in config.SUB_BREAK_PUNCT
        if (end_punct and len(txt) >= config.SUB_MIN_BREAK) or len(txt) >= config.SUB_MAX_CHARS:
            units.append(cur); cur = []
    if cur:
        units.append(cur)
    cards = []
    for i, u in enumerate(units):
        start = u[0][0] + scene["head"]
        end = u[-1][1] + scene["head"] + 0.06
        if i + 1 < len(units):
            end = min(end, units[i + 1][0][0] + scene["head"] - 0.02)
        img = subtitle_card(u)
        p = ovl_dir / f"sub_s{scene['id']}_{i}.png"
        img.save(p)
        cards.append({"png": str(p), "start": round(max(0, start), 3),
                      "end": round(min(end, scene["dur"]), 3),
                      "w": img.width, "h": img.height})
    return cards
