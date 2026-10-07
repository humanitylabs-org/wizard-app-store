#!/usr/bin/env python3
"""Neutral, configurable caption overlay adapter for a locked DeFleur timeline."""
from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path
from typing import Callable


def _color(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError("caption colors must be #RRGGBB")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def _chunks(words: list[dict], maximum_words: int, maximum_chars: int) -> list[list[int]]:
    result, current, length = [], [], 0
    for index, word in enumerate(words):
        token = str(word.get("word", "")).strip()
        next_length = length + len(token) + (1 if current else 0)
        if current and (len(current) >= maximum_words or next_length > maximum_chars):
            result.append(current); current = []; length = 0
        current.append(index); length += len(token) + (1 if len(current) > 1 else 0)
    if current:
        result.append(current)
    return result


def caption_engine(project: Path, style_path: Path | None = None) -> Callable:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Install Pillow on the media worker.") from exc
    timeline = json.loads((project / "locked-timeline.json").read_text(encoding="utf-8"))
    style_file = style_path or project / "caption-style.json"
    style = json.loads(style_file.read_text(encoding="utf-8"))
    style = style.get("caption", style)
    words = timeline.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("locked timeline needs words")
    required = ("font_path", "font_size_px", "max_words", "max_chars", "text_color", "active_color", "outline_color", "outline_width_px", "safe_rect")
    if any(key not in style for key in required):
        raise ValueError("caption style is incomplete")
    font_file = Path(str(style["font_path"])).expanduser()
    if not font_file.is_file():
        raise ValueError("caption style font_path must name an existing worker/project font")
    font = ImageFont.truetype(str(font_file), int(style["font_size_px"]))
    colors = _color(str(style["text_color"])), _color(str(style["active_color"])), _color(str(style["outline_color"]))
    outline = int(style["outline_width_px"])
    left, top, right, bottom = [int(value) for value in style["safe_rect"]]
    if left >= right or top >= bottom or outline < 0:
        raise ValueError("invalid caption safe rectangle")
    chunks = _chunks(words, int(style["max_words"]), int(style["max_chars"]))
    starts = [float(word["start"]) for word in words]
    if starts != sorted(starts) or any(float(w['end']) <= float(w['start']) for w in words):
        raise ValueError('Caption word timings must be ordered and positive')
    plan_file = project / 'visual-plan.json'
    plan = json.loads(plan_file.read_text()) if plan_file.exists() else {}
    suppress = timeline.get('caption_suppressions', timeline.get('caption_suppress', plan.get('caption_suppressions', plan.get('caption_suppress', []))))

    def draw(image, time_s: float):
        if any(float(row["start"]) <= time_s < float(row["end"]) for row in suppress):
            return image
        if time_s < starts[0] or time_s >= float(words[-1]['end']):
            return image
        active = bisect.bisect_right(starts, time_s) - 1
        selected = next((chunk for chunk in chunks if active in chunk), None)
        if not selected or time_s >= float(words[selected[-1]]['end']):
            return image
        canvas = image.convert('RGBA')
        overlay = Image.new('RGBA', canvas.size)
        painter = ImageDraw.Draw(overlay)
        # Wrap actual measured text; fail instead of silently drawing outside the safe box.
        margin = outline + 2
        available = right - left - 2 * margin
        lines, line, width = [], [], 0
        spacing = painter.textlength(' ',font=font)
        for index in selected:
            token = str(words[index].get('word','')).strip()
            size = painter.textlength(token,font=font)
            if size > available: raise ValueError('Caption token exceeds safe width; revise chunk/font before encoding')
            if line and width + spacing + size > available:
                lines.append((line,width)); line=[]; width=0
            width += (spacing if line else 0) + size
            line.append((index,token,size))
        if line: lines.append((line,width))
        line_height = sum(font.getmetrics()) + outline * 2
        if len(lines) * line_height > bottom - top - 2 * margin:
            raise ValueError('Caption exceeds safe height; revise chunk/font before encoding')
        y = top + (bottom - top - len(lines) * line_height) / 2
        for line,width in lines:
            x=left+(right-left-width)/2
            for index,token,size in line:
                painter.text((x,y),token,font=font,anchor='lt',fill=colors[1] if index==active else colors[0],stroke_width=outline,stroke_fill=colors[2])
                x += size + spacing
            y += line_height
        box=overlay.getbbox()
        if box and (box[0]<left or box[1]<top or box[2]>right or box[3]>bottom):
            raise ValueError('Rendered caption exceeds safe bounds')
        return Image.alpha_composite(canvas,overlay).convert(image.mode)

    return draw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("input_image", type=Path)
    parser.add_argument("output_image", type=Path)
    parser.add_argument("--time", required=True, type=float)
    parser.add_argument("--style", type=Path)
    args = parser.parse_args()
    from PIL import Image
    rendered = caption_engine(args.project, args.style)(Image.open(args.input_image), args.time)
    args.output_image.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(args.output_image)


if __name__ == "__main__":
    main()
