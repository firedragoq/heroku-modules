__version__ = (2, 18, 4)

# meta developer: @dragomodules
# scope: heroku_only
# changelog: иконка 🎵 в каталоге (ведущий эмодзи в описании)
# scope: heroku_min 1.7.2
# requires: aiohttp pillow>=10.0.0 git+https://github.com/MarshalX/yandex-music-api

import asyncio
import html
import io
import json
import logging
import math
import re
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import telethon
import yandex_music
import yandex_music.exceptions
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .. import loader, utils


logger = logging.getLogger(__name__)

REDIRECTOR_URL = (
    "wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/"
    "GetRedirectToYnison"
)
STATE_PATH = "/ynison_state.YnisonStateService/PutYnisonState"


class FiredBanner:
    """Local banner renderer for the currently playing Yandex Music track."""

    WIDTH = 1920
    HEIGHT = 960
    SVG_ICONS = {
        "yandex_music": (
            '<svg width="448" height="445" viewBox="0 0 448 445" fill="none" xmlns="http://www.w3.org/2000/svg">'
            '<path d="M442.973 173.499L441.756 164.528L368.261 147.37L406.225 91.0325L401.739 84.9248L342.538 113.892L349.076 35.1002L342.538 31.8563L305.79 95.1128L262.529 0H254.369L264.962 93.0853L156.773 6.94402L147.396 9.4023L230.673 113.892L65.3346 58.7961L57.5796 67.362L205.355 151.045L2.05279 168.202L0 180.443L211.488 203.303L34.7201 347.834L42.8806 358.859L252.316 244.536L211.083 445H223.729L304.574 256.396L353.562 403.767L362.128 397.228L343.754 249.452L418.466 333.946L422.977 325.38L367.45 220.865L446.242 248.641L447.053 240.05L381.338 187.387L442.973 173.499Z" fill="#FED42B"/>'
            '</svg>'
        ),
        "title": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="8" cy="18" r="4"/>'
            '<path d="M12 18V2l7 4"/>'
            '</svg>'
        ),
        "artist": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12 19v3"/>'
            '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'
            '<rect x="9" y="2" width="6" height="13" rx="3"/>'
            '</svg>'
        ),
        "album": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/>'
            '<path d="M6 12c0-1.7.7-3.2 1.8-4.2"/>'
            '<circle cx="12" cy="12" r="2"/>'
            '<path d="M18 12c0 1.7-.7 3.2-1.8 4.2"/>'
            '</svg>'
        ),
        "calendar": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M8 2v4"/>'
            '<path d="M16 2v4"/>'
            '<rect width="18" height="18" x="3" y="4" rx="2"/>'
            '<path d="M3 10h18"/>'
            '<path d="M8 14h.01"/>'
            '<path d="M12 14h.01"/>'
            '<path d="M16 14h.01"/>'
            '<path d="M8 18h.01"/>'
            '<path d="M12 18h.01"/>'
            '<path d="M16 18h.01"/>'
            '</svg>'
        ),
        "monitor": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<rect width="20" height="14" x="2" y="3" rx="2"/>'
            '<line x1="8" x2="16" y1="21" y2="21"/>'
            '<line x1="12" x2="12" y1="17" y2="21"/>'
            '</svg>'
        ),
    }

    def __init__(
        self,
        title: str,
        artist: str,
        album: str,
        duration_ms: int,
        progress_ms: int,
        cover_bytes: bytes,
        device: str,
        meta: str,
        paused: bool,
        blur: int = 18,
    ):
        self.title = title
        self.artist = artist
        self.album = album
        self.duration_ms = duration_ms
        self.progress_ms = progress_ms
        self.cover_bytes = cover_bytes
        self.device = device
        self.meta = meta
        self.paused = paused
        self.blur = blur

    def render(self) -> io.BytesIO:
        cover = self._open_cover()
        accent = self._accent(cover)
        bg = self._make_background(cover, accent)
        draw = ImageDraw.Draw(bg)

        cover_size = 560
        cover_x = 110
        cover_y = 190
        radius = 54
        panel = (735, 105, 1810, 855)

        panel_layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel_layer)
        panel_draw.rounded_rectangle(panel, radius=44, fill=(9, 12, 19, 156))
        panel_draw.rounded_rectangle(panel, radius=44, outline=accent + (92,), width=2)
        bg = Image.alpha_composite(bg, panel_layer)
        draw = ImageDraw.Draw(bg)

        shadow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle(
            (cover_x - 14, cover_y + 18, cover_x + cover_size + 14, cover_y + cover_size + 40),
            radius=radius + 12,
            fill=(0, 0, 0, 165),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(28))
        bg = Image.alpha_composite(bg, shadow)

        cover_img = self._crop_square(cover).resize((cover_size, cover_size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (cover_size, cover_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cover_size, cover_size), radius=radius, fill=255)
        bg.paste(cover_img, (cover_x, cover_y), mask)

        border = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        border_draw = ImageDraw.Draw(border)
        border_draw.rounded_rectangle(
            (cover_x, cover_y, cover_x + cover_size, cover_y + cover_size),
            radius=radius,
            outline=(255, 255, 255, 92),
            width=4,
        )
        bg = Image.alpha_composite(bg, border)
        draw = ImageDraw.Draw(bg)

        content_x = 800
        content_w = 925
        y = 155

        small_font = self._font(36)
        meta_font = self._font(39)
        album_font = self._font(39)

        self._brand(draw, content_x, y, accent)
        self._state_dot(draw, content_x + 92, y + 25, accent)

        y += 110
        self._plain_svg(draw, content_x, y + 28, "title", 38, accent)
        text_x = content_x + 62
        # правый отступ, чтобы текст не упирался в рамку карточки
        text_w = content_w - 62 - 28
        # сначала пытаемся уместить заголовок в ОДНУ строку (уменьшая шрифт),
        # и только если совсем длинно — переносим мелким шрифтом на 2 строки
        title_font, title_lines = self._fit_one_or_wrap(
            self.title, text_w, one_max=86, one_min=46, wrap_size=52, wrap_min=36
        )
        title_lh = int(title_font.size * 1.14)
        for line in title_lines:
            self._shadow_text(draw, (text_x, y), line, title_font, (255, 255, 255, 255))
            y += title_lh

        y += 6
        self._plain_svg(draw, content_x, y + 12, "artist", 36, accent)
        artist_font, artist_lines = self._fit_one_or_wrap(
            self.artist, text_w, one_max=54, one_min=40, wrap_size=46, wrap_min=32
        )
        artist_lh = int(artist_font.size * 1.18)
        for line in artist_lines:
            self._shadow_text(draw, (text_x, y), line, artist_font, (238, 244, 255, 245))
            y += artist_lh

        y += 22
        album = self._fit(self.album, album_font, content_w - 58)
        self._small_icon(draw, content_x, y + 5, "album", accent)
        draw.text((content_x + 58, y), album, font=album_font, fill=(225, 231, 240, 218))
        y += 58

        meta = self._fit(self.meta, meta_font, content_w - 58)
        self._small_icon(draw, content_x, y + 5, "meta", accent)
        draw.text((content_x + 58, y), meta, font=meta_font, fill=(225, 231, 240, 180))
        y += 102

        self._progress(draw, content_x, y, content_w, accent)
        y += 96

        device = self._fit(self.device, small_font, content_w - 58)
        self._small_icon(draw, content_x, y + 4, "device", accent)
        draw.text((content_x + 58, y), device, font=small_font, fill=(225, 231, 240, 184))

        out = io.BytesIO()
        bg.convert("RGB").save(out, format="PNG", optimize=True)
        out.seek(0)
        out.name = "yamusic_firedragoq.png"
        return out

    def _open_cover(self) -> Image.Image:
        try:
            return Image.open(io.BytesIO(self.cover_bytes)).convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (1000, 1000), (16, 18, 22, 255))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((160, 160, 840, 840), radius=90, fill=(55, 65, 82, 255))
            draw.ellipse((390, 280, 610, 500), fill=(230, 236, 245, 180))
            draw.rectangle((485, 410, 535, 710), fill=(230, 236, 245, 180))
            draw.ellipse((390, 620, 540, 770), fill=(230, 236, 245, 180))
            return img

    def _make_background(self, cover: Image.Image, accent: Tuple[int, int, int]) -> Image.Image:
        base = self._cover_fill(cover, self.WIDTH, self.HEIGHT)
        base = base.filter(ImageFilter.GaussianBlur(max(12, int(self.blur))))
        base = ImageEnhance.Color(base).enhance(1.35)
        base = ImageEnhance.Contrast(base).enhance(1.08)
        base.putalpha(122)

        bg = Image.new("RGBA", base.size, (10, 13, 21, 255))
        bg = Image.alpha_composite(bg, base)

        glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        secondary = self._secondary(accent)
        glow_draw.ellipse((-360, -260, 1000, 950), fill=accent + (125,))
        glow_draw.ellipse((1020, -320, 2280, 760), fill=secondary + (84,))
        glow_draw.ellipse((420, 610, 1380, 1240), fill=accent + (52,))
        glow = glow.filter(ImageFilter.GaussianBlur(120))
        bg = Image.alpha_composite(bg, glow)

        shade = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        shade_draw = ImageDraw.Draw(shade)
        shade_draw.rectangle((0, 0, self.WIDTH, self.HEIGHT), fill=(0, 0, 0, 82))
        shade_draw.rectangle((700, 0, self.WIDTH, self.HEIGHT), fill=(0, 0, 0, 68))
        return Image.alpha_composite(bg, shade)

    def _cover_fill(self, image: Image.Image, width: int, height: int) -> Image.Image:
        img = image.convert("RGBA")
        src_w, src_h = img.size
        ratio = max(width / src_w, height / src_h)
        new_size = (int(src_w * ratio), int(src_h * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        left = (img.width - width) // 2
        top = (img.height - height) // 2
        return img.crop((left, top, left + width, top + height))

    def _crop_square(self, image: Image.Image) -> Image.Image:
        side = min(image.size)
        left = (image.width - side) // 2
        top = (image.height - side) // 2
        return image.crop((left, top, left + side, top + side))

    def _accent(self, image: Image.Image) -> Tuple[int, int, int]:
        small = image.convert("RGB").resize((90, 90), Image.Resampling.LANCZOS)
        best = (255, 196, 0)
        best_score = -1.0

        for r, g, b in small.getdata():
            high = max(r, g, b)
            low = min(r, g, b)
            saturation = high - low
            brightness = (r * 299 + g * 587 + b * 114) / 1000
            if saturation < 28 or brightness < 34 or brightness > 245:
                continue
            score = saturation * 1.8 + min(brightness, 215) * 0.35
            if score > best_score:
                best = (r, g, b)
                best_score = score

        r, g, b = best
        brightness = (r * 299 + g * 587 + b * 114) // 1000
        if brightness < 86:
            r, g, b = min(r + 72, 255), min(g + 72, 255), min(b + 72, 255)
        return r, g, b

    def _secondary(self, color: Tuple[int, int, int]) -> Tuple[int, int, int]:
        r, g, b = color
        return (
            min(255, int(b * 0.65 + 74)),
            min(255, int(r * 0.45 + 78)),
            min(255, int(g * 0.55 + 112)),
        )

    def _font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _text_w(self, text: str, font: ImageFont.ImageFont) -> int:
        left, _, right, _ = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
        return right - left

    def _fit(self, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
        if self._text_w(text, font) <= max_width:
            return text
        ellipsis = "..."
        while text and self._text_w(text + ellipsis, font) > max_width:
            text = text[:-1]
        return (text or " ") + ellipsis

    def _shadow_text(
        self,
        draw: ImageDraw.ImageDraw,
        pos: Tuple[int, int],
        text: str,
        font: ImageFont.ImageFont,
        fill: Tuple[int, int, int, int],
    ):
        x, y = pos
        draw.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 120))
        draw.text((x, y), text, font=font, fill=fill)

    def _wrap(
        self,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
        max_lines: int = 2,
    ) -> List[str]:
        words = text.split() or [text]
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if not current or self._text_w(candidate, font) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) == max_lines:
            lines[-1] = self._fit(lines[-1], font, max_width)
        return lines or [self._fit(text, font, max_width)]

    def _wrap_all(
        self, text: str, font: ImageFont.ImageFont, max_width: int
    ) -> List[str]:
        """Перенос без ограничения числа строк (для авто-подбора шрифта)."""
        lines: List[str] = []
        current = ""
        for word in (text.split() or [text]):
            candidate = f"{current} {word}".strip()
            if not current or self._text_w(candidate, font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [text]

    def _fit_one_or_wrap(
        self,
        text: str,
        max_width: int,
        one_max: int,
        one_min: int,
        wrap_size: int,
        wrap_min: int,
    ) -> Tuple[ImageFont.ImageFont, List[str]]:
        """Сначала пытается уместить текст в ОДНУ строку (уменьшая шрифт от
        one_max до one_min). Если не выходит — переносит на 2 строки шрифтом
        wrap_size (с авто-уменьшением до wrap_min)."""
        text = text.strip()
        size = one_max
        while size >= one_min:
            font = self._font(size, bold=True)
            if self._text_w(text, font) <= max_width:
                return font, [text]
            size -= 4
        return self._fit_font(
            text, max_width, max_lines=2, start_size=wrap_size,
            min_size=wrap_min, bold=True,
        )

    def _fit_font(
        self,
        text: str,
        max_width: int,
        max_lines: int,
        start_size: int,
        min_size: int,
        bold: bool = False,
    ) -> Tuple[ImageFont.ImageFont, List[str]]:
        """Подбирает размер шрифта, чтобы текст уместился в max_lines строк."""
        size = start_size
        while size > min_size:
            font = self._font(size, bold=bold)
            lines = self._wrap_all(text, font, max_width)
            if len(lines) <= max_lines and all(
                self._text_w(ln, font) <= max_width for ln in lines
            ):
                return font, lines
            size -= 4
        font = self._font(min_size, bold=bold)
        return font, self._wrap(text, font, max_width, max_lines)

    def _brand(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        accent: Tuple[int, int, int],
    ):
        size = 72
        draw.rounded_rectangle((x, y, x + size, y + size), radius=22, fill=(10, 13, 20, 230))
        draw.rounded_rectangle((x, y, x + size, y + size), radius=22, outline=accent + (140,), width=2)
        self._paste_svg(draw.im, "yandex_music", x + 14, y + 14, 44, 44, accent + (255,))

    def _state_dot(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        accent: Tuple[int, int, int],
    ):
        fill = (245, 112, 112, 235) if self.paused else accent + (235,)
        draw.ellipse((x, y, x + 18, y + 18), fill=fill)

    def _small_icon(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        kind: str,
        accent: Tuple[int, int, int],
    ):
        icon_name = {"album": "album", "meta": "calendar", "device": "monitor"}.get(kind, "album")
        self._svg_shadow(draw.im, icon_name, x + 1, y + 1, 36, 36, (0, 0, 0, 88))
        self._paste_svg(draw.im, icon_name, x, y, 36, 36, (238, 244, 255, 225))

    def _plain_svg(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        name: str,
        size: int,
        accent: Tuple[int, int, int],
    ):
        self._svg_shadow(draw.im, name, x + 2, y + 2, size, size, (0, 0, 0, 95))
        self._paste_svg(draw.im, name, x, y, size, size, (238, 244, 255, 235))

    def _svg_shadow(
        self,
        image_core: Any,
        name: str,
        x: int,
        y: int,
        width: int,
        height: int,
        color: Tuple[int, int, int, int],
    ):
        icon = self._render_svg_icon(name, width, height, color).filter(ImageFilter.GaussianBlur(1.2))
        Image.Image()._new(image_core).alpha_composite(icon, (x, y))

    def _paste_svg(
        self,
        image_core: Any,
        name: str,
        x: int,
        y: int,
        width: int,
        height: int,
        color: Tuple[int, int, int, int],
    ):
        icon = self._render_svg_icon(name, width, height, color)
        Image.Image()._new(image_core).alpha_composite(icon, (x, y))

    def _render_svg_icon(
        self,
        name: str,
        width: int,
        height: int,
        color: Tuple[int, int, int, int],
    ) -> Image.Image:
        root = ET.fromstring(self.SVG_ICONS[name])
        view_box = root.attrib.get("viewBox", "0 0 24 24").replace(",", " ").split()
        min_x, min_y, vb_w, vb_h = [float(v) for v in view_box[:4]]
        root_fill = root.attrib.get("fill")
        root_stroke = root.attrib.get("stroke")
        root_stroke_width = root.attrib.get("stroke-width", "2")
        scale = min(width / vb_w, height / vb_h)
        offset_x = (width - vb_w * scale) / 2
        offset_y = (height - vb_h * scale) / 2
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def xy(px: str, py: str) -> Tuple[float, float]:
            return (
                (float(px) - min_x) * scale + offset_x,
                (float(py) - min_y) * scale + offset_y,
            )

        def sw(node: ET.Element) -> int:
            return max(1, int(round(float(node.attrib.get("stroke-width", root_stroke_width)) * scale)))

        def paint(value: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
            if not value or value == "none":
                return None
            if value == "currentColor":
                return color
            if value.startswith("#") and len(value) in {4, 7}:
                if len(value) == 4:
                    r, g, b = [int(ch * 2, 16) for ch in value[1:]]
                else:
                    r = int(value[1:3], 16)
                    g = int(value[3:5], 16)
                    b = int(value[5:7], 16)
                return r, g, b, color[3]
            return color

        for node in root:
            tag = node.tag.split("}", 1)[-1]
            stroke = paint(node.attrib.get("stroke", root_stroke))
            fill = paint(node.attrib.get("fill", root_fill))

            if tag == "line":
                start = xy(node.attrib["x1"], node.attrib["y1"])
                end = xy(node.attrib["x2"], node.attrib["y2"])
                draw.line((start, end), fill=stroke or color, width=sw(node))
            elif tag == "circle":
                cx, cy = xy(node.attrib["cx"], node.attrib["cy"])
                r = float(node.attrib["r"]) * scale
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=stroke, width=sw(node))
            elif tag == "rect":
                x1, y1 = xy(node.attrib["x"], node.attrib["y"])
                width = float(node.attrib["width"]) * scale
                height = float(node.attrib["height"]) * scale
                radius = int(float(node.attrib.get("rx", "0")) * scale)
                draw.rounded_rectangle(
                    (x1, y1, x1 + width, y1 + height),
                    radius=radius,
                    fill=fill,
                    outline=stroke,
                    width=sw(node),
                )
            elif tag in {"polyline", "polygon"}:
                nums = node.attrib.get("points", "").replace(",", " ").split()
                points = [
                    ((float(nums[i]) - min_x) * scale, (float(nums[i + 1]) - min_y) * scale)
                    for i in range(0, len(nums) - 1, 2)
                ]
                if tag == "polygon":
                    draw.polygon(points, fill=fill, outline=stroke)
                elif len(points) > 1:
                    draw.line(points, fill=stroke or color, width=sw(node), joint="curve")
            elif tag == "path":
                self._draw_svg_path(draw, node.attrib.get("d", ""), fill, stroke, sw(node), xy, scale, offset_x, offset_y)

        return img

    def _draw_svg_path(
        self,
        draw: ImageDraw.ImageDraw,
        d: str,
        fill: Optional[Tuple[int, int, int, int]],
        stroke: Optional[Tuple[int, int, int, int]],
        stroke_width: int,
        xy,
        scale: float,
        offset_x: float,
        offset_y: float,
    ):
        tokens = [
            match.group(0)
            for match in re.finditer(
                r"[MmLlHhVvCcQqZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?",
                d,
            )
        ]
        if not tokens:
            return

        def is_cmd(value: str) -> bool:
            return len(value) == 1 and value.isalpha()

        def point(px: float, py: float) -> Tuple[float, float]:
            return xy(str(px), str(py))

        def cubic(p0, p1, p2, p3, steps: int = 18):
            out = []
            for idx in range(1, steps + 1):
                t = idx / steps
                mt = 1 - t
                x = (
                    mt * mt * mt * p0[0]
                    + 3 * mt * mt * t * p1[0]
                    + 3 * mt * t * t * p2[0]
                    + t * t * t * p3[0]
                )
                y = (
                    mt * mt * mt * p0[1]
                    + 3 * mt * mt * t * p1[1]
                    + 3 * mt * t * t * p2[1]
                    + t * t * t * p3[1]
                )
                out.append((x, y))
            return out

        def quadratic(p0, p1, p2, steps: int = 14):
            out = []
            for idx in range(1, steps + 1):
                t = idx / steps
                mt = 1 - t
                out.append(
                    (
                        mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                        mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
                    )
                )
            return out

        def arc_points(start_raw, end_raw, rx, ry, rotation, large_arc, sweep, steps: int = 18):
            if rx == 0 or ry == 0:
                return [point(*end_raw)]

            x1, y1 = start_raw
            x2, y2 = end_raw
            phi = math.radians(rotation % 360)
            cos_phi = math.cos(phi)
            sin_phi = math.sin(phi)
            dx = (x1 - x2) / 2
            dy = (y1 - y2) / 2
            x1p = cos_phi * dx + sin_phi * dy
            y1p = -sin_phi * dx + cos_phi * dy
            rx = abs(rx)
            ry = abs(ry)

            lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
            if lam > 1:
                factor = math.sqrt(lam)
                rx *= factor
                ry *= factor

            numerator = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
            denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
            factor = 0.0 if denominator == 0 else math.sqrt(max(0.0, numerator / denominator))
            if large_arc == sweep:
                factor = -factor

            cxp = factor * (rx * y1p / ry)
            cyp = factor * (-ry * x1p / rx)
            cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2
            cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2

            def angle(u, v):
                dot = u[0] * v[0] + u[1] * v[1]
                det = u[0] * v[1] - u[1] * v[0]
                return math.atan2(det, dot)

            start_vec = ((x1p - cxp) / rx, (y1p - cyp) / ry)
            end_vec = ((-x1p - cxp) / rx, (-y1p - cyp) / ry)
            theta1 = angle((1, 0), start_vec)
            delta = angle(start_vec, end_vec)
            if not sweep and delta > 0:
                delta -= 2 * math.pi
            elif sweep and delta < 0:
                delta += 2 * math.pi

            count = max(8, int(abs(delta) / (math.pi / 14)))
            out = []
            for arc_idx in range(1, count + 1):
                theta = theta1 + delta * arc_idx / count
                xp = rx * math.cos(theta)
                yp = ry * math.sin(theta)
                x = cos_phi * xp - sin_phi * yp + cx
                y = sin_phi * xp + cos_phi * yp + cy
                out.append(point(x, y))
            return out

        idx = 0
        cmd = ""
        current = (0.0, 0.0)
        start = (0.0, 0.0)
        path: List[Tuple[float, float]] = []
        paths: List[List[Tuple[float, float]]] = []

        def read_float() -> float:
            nonlocal idx
            value = float(tokens[idx])
            idx += 1
            return value

        def push_path():
            nonlocal path
            if len(path) > 1:
                paths.append(path)
            path = []

        while idx < len(tokens):
            if is_cmd(tokens[idx]):
                cmd = tokens[idx]
                idx += 1
            if not cmd:
                break
            before_idx = idx

            if cmd in "Mm":
                first = True
                while idx + 1 < len(tokens) and not is_cmd(tokens[idx]):
                    x = read_float()
                    y = read_float()
                    if cmd == "m":
                        x += current[0]
                        y += current[1]
                    current = (x, y)
                    if first:
                        push_path()
                        start = current
                        path = [point(*current)]
                        first = False
                    else:
                        path.append(point(*current))
                cmd = "l" if cmd == "m" else "L"

            elif cmd in "Ll":
                while idx + 1 < len(tokens) and not is_cmd(tokens[idx]):
                    x = read_float()
                    y = read_float()
                    if cmd == "l":
                        x += current[0]
                        y += current[1]
                    current = (x, y)
                    path.append(point(*current))

            elif cmd in "Hh":
                while idx < len(tokens) and not is_cmd(tokens[idx]):
                    x = read_float()
                    if cmd == "h":
                        x += current[0]
                    current = (x, current[1])
                    path.append(point(*current))

            elif cmd in "Vv":
                while idx < len(tokens) and not is_cmd(tokens[idx]):
                    y = read_float()
                    if cmd == "v":
                        y += current[1]
                    current = (current[0], y)
                    path.append(point(*current))

            elif cmd in "Cc":
                while idx + 5 < len(tokens) and not is_cmd(tokens[idx]):
                    c1 = (read_float(), read_float())
                    c2 = (read_float(), read_float())
                    end = (read_float(), read_float())
                    if cmd == "c":
                        c1 = (c1[0] + current[0], c1[1] + current[1])
                        c2 = (c2[0] + current[0], c2[1] + current[1])
                        end = (end[0] + current[0], end[1] + current[1])
                    path.extend(cubic(point(*current), point(*c1), point(*c2), point(*end)))
                    current = end

            elif cmd in "Qq":
                while idx + 3 < len(tokens) and not is_cmd(tokens[idx]):
                    c1 = (read_float(), read_float())
                    end = (read_float(), read_float())
                    if cmd == "q":
                        c1 = (c1[0] + current[0], c1[1] + current[1])
                        end = (end[0] + current[0], end[1] + current[1])
                    path.extend(quadratic(point(*current), point(*c1), point(*end)))
                    current = end

            elif cmd in "Aa":
                while idx + 6 < len(tokens) and not is_cmd(tokens[idx]):
                    rx = read_float()
                    ry = read_float()
                    rotation = read_float()
                    large_arc = bool(int(read_float()))
                    sweep = bool(int(read_float()))
                    end = (read_float(), read_float())
                    if cmd == "a":
                        end = (end[0] + current[0], end[1] + current[1])
                    path.extend(arc_points(current, end, rx, ry, rotation, large_arc, sweep))
                    current = end

            elif cmd in "Zz":
                if path:
                    path.append(point(*start))
                    push_path()
                current = start
                cmd = ""

            else:
                break

            if idx == before_idx and cmd not in "Zz":
                break

        push_path()

        for item in paths:
            if fill and len(item) > 2:
                draw.polygon(item, fill=fill)
            if stroke and len(item) > 1:
                if len(item) == 2 and abs(item[0][0] - item[1][0]) + abs(item[0][1] - item[1][1]) <= stroke_width:
                    px, py = item[0]
                    radius = stroke_width / 2
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=stroke)
                else:
                    draw.line(item, fill=stroke, width=stroke_width, joint="curve")

    def _progress(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        accent: Tuple[int, int, int],
    ):
        bar_h = 12
        duration = max(self.duration_ms, 1)
        ratio = min(max(self.progress_ms / duration, 0), 1)
        filled = int(width * ratio)

        time_font = self._font(32)
        draw.rounded_rectangle((x, y, x + width, y + bar_h), radius=bar_h // 2, fill=(255, 255, 255, 54))
        draw.rounded_rectangle((x, y, x + filled, y + bar_h), radius=bar_h // 2, fill=accent + (255,))
        draw.ellipse((x + filled - 13, y - 8, x + filled + 13, y + 18), fill=(255, 255, 255, 252))
        draw.ellipse((x + filled - 7, y - 2, x + filled + 7, y + 12), fill=accent + (255,))

        draw.text((x, y + 28), self._format_time(self.progress_ms), font=time_font, fill=(236, 240, 248, 210))
        total = self._format_time(self.duration_ms)
        total_w = self._text_w(total, time_font)
        draw.text((x + width - total_w, y + 28), total, font=time_font, fill=(236, 240, 248, 210))

    def _format_time(self, ms: int) -> str:
        seconds = max(0, int(ms // 1000))
        return f"{seconds // 60}:{seconds % 60:02d}"


@loader.tds
class DragoYAMusicMod(loader.Module):
    """🎵 Yandex Music tools: current track, banner, audio, likes, lyrics and autobio."""

    TRACK_EMOJI = "<emoji document_id=5350279866304445948>🔥</emoji>"
    DEVICE_EMOJI = "<emoji document_id=5348421451135336104>👾</emoji>"
    VOLUME_EMOJI = "<emoji document_id=6039454987250044861>🔊</emoji>"
    FROM_EMOJI = "<emoji document_id=5350695039318114023>🔗</emoji>"
    LINK_EMOJI = "<emoji document_id=5346296430166293639>📱</emoji>"
    LOADING_EMOJI = "<emoji document_id=5242574232688298747>🎵</emoji>"

    strings = {
        "name": "DragoYAMusic",
        "_cls_doc": "🎵 Yandex Music tools: current track, banner, audio, likes, lyrics and autobio.",
        "guide": (
            "<b>DragoYAMusic by @firedragoq</b>\n\n"
            "<code>.dt TOKEN</code> / <code>.dyatoken</code> - save OAuth token\n"
            "<code>.ds</code> / <code>.dyas</code> - check token\n"
            "<code>.dn</code> / <code>.dyan</code> - current track with banner\n"
            "<code>.da</code> / <code>.dyat</code> - send current track audio\n"
            "<code>.dq query</code> / <code>.dyaq</code> - search and send track\n"
            "<code>.dl</code> / <code>.dyalike</code> - like track\n"
            "<code>.du</code> / <code>.dyaunlike</code> - unlike track\n"
            "<code>.dd</code> / <code>.dyadislike</code> - dislike track\n"
            "<code>.dr</code> / <code>.dyalyr</code> - current lyrics\n"
            "<code>.dv</code> / <code>.dyalive</code> - live synced lyrics\n"
            "<code>.db</code> / <code>.dyab</code> - toggle autobio\n"
            "<code>.dk</code> / <code>.dyalink</code> - current link\n"
            "<code>.dm</code> / <code>.dyad</code> - safe diagnostics\n"
            "<code>.dg</code> / <code>.dyag</code> - this guide\n\n"
            "Token guide: "
            "<a href=\"https://yandex-music.readthedocs.io/en/main/token.html\">"
            "yandex-music.readthedocs.io</a>"
        ),
        "no_token": "<b>Set Yandex Music token first:</b> <code>.dyatoken TOKEN</code>",
        "bad_token": "<b>Could not authorize in Yandex Music. Check the token.</b>",
        "saved": "<b>Token saved.</b>",
        "checking": LOADING_EMOJI,
        "connected": "<b>Yandex Music is connected.</b>",
        "loading": LOADING_EMOJI,
        "not_playing": "<b>You are not listening to anything now.</b>",
        "paused": "<b>Yandex Music is paused.</b>",
        "uploading_banner": LOADING_EMOJI,
        "downloading_track": LOADING_EMOJI,
        "no_query": "<b>Give me a search query.</b>",
        "not_found": "<b>Nothing found.</b>",
        "download_error": "<b>Could not download this track.</b>",
        "liked": "<b>Liked:</b> <a href=\"{url}\">{track}</a>",
        "unliked": "<b>Unliked:</b> <a href=\"{url}\">{track}</a>",
        "disliked": "<b>Disliked:</b> <a href=\"{url}\">{track}</a>",
        "no_lyrics": "<b>No lyrics for:</b> <a href=\"{url}\">{track}</a>",
        "no_synced_lyrics": "<b>No synced lyrics for:</b> <a href=\"{url}\">{track}</a>",
        "live_lyrics_loading": LOADING_EMOJI,
        "lyrics": "<b>Lyrics:</b> <a href=\"{url}\">{track}</a>\n\n<pre>{text}</pre>",
        "autobio_enabled": "<b>Autobio enabled.</b>",
        "autobio_disabled": "<b>Autobio disabled.</b>",
        "debugging": LOADING_EMOJI,
        "now_listening_label": "Now listening on",
        "playing_from_label": "Playing from:",
        "yandex_music_link": "Yandex Music",
    }

    strings_ru = {
        "name": "DragoYAMusic",
        "_cls_doc": "🎵 Инструменты Яндекс Музыки: текущий трек, баннер, аудио, лайки, текст и autobio.",
        "guide": (
            "<b>DragoYAMusic by @firedragoq</b>\n\n"
            "<code>.dt TOKEN</code> / <code>.dyatoken</code> - сохранить OAuth-токен\n"
            "<code>.ds</code> / <code>.dyas</code> - проверить токен\n"
            "<code>.dn</code> / <code>.dyan</code> - текущий трек с баннером\n"
            "<code>.da</code> / <code>.dyat</code> - отправить текущий трек аудио\n"
            "<code>.dq запрос</code> / <code>.dyaq</code> - найти и отправить трек\n"
            "<code>.dl</code> / <code>.dyalike</code> - лайкнуть трек\n"
            "<code>.du</code> / <code>.dyaunlike</code> - убрать лайк\n"
            "<code>.dd</code> / <code>.dyadislike</code> - дизлайкнуть трек\n"
            "<code>.dr</code> / <code>.dyalyr</code> - текст текущего трека\n"
            "<code>.dv</code> / <code>.dyalive</code> - живой текст по таймкодам\n"
            "<code>.db</code> / <code>.dyab</code> - включить/выключить autobio\n"
            "<code>.dk</code> / <code>.dyalink</code> - ссылка на текущий трек\n"
            "<code>.dm</code> / <code>.dyad</code> - безопасная диагностика\n"
            "<code>.dg</code> / <code>.dyag</code> - этот гайд\n\n"
            "Гайд по токену: "
            "<a href=\"https://yandex-music.readthedocs.io/en/main/token.html\">"
            "yandex-music.readthedocs.io</a>"
        ),
        "no_token": "<b>Сначала укажи токен Яндекс Музыки:</b> <code>.dyatoken TOKEN</code>",
        "bad_token": "<b>Не удалось войти в Яндекс Музыку. Проверь токен.</b>",
        "saved": "<b>Токен сохранен.</b>",
        "checking": LOADING_EMOJI,
        "connected": "<b>Яндекс Музыка подключена.</b>",
        "loading": LOADING_EMOJI,
        "not_playing": "<b>Вы ничего не слушаете сейчас.</b>",
        "paused": "<b>Яндекс Музыка стоит на паузе.</b>",
        "uploading_banner": LOADING_EMOJI,
        "downloading_track": LOADING_EMOJI,
        "no_query": "<b>Напиши поисковый запрос.</b>",
        "not_found": "<b>Ничего не найдено.</b>",
        "download_error": "<b>Не удалось скачать этот трек.</b>",
        "liked": "<b>Лайкнул:</b> <a href=\"{url}\">{track}</a>",
        "unliked": "<b>Убрал лайк:</b> <a href=\"{url}\">{track}</a>",
        "disliked": "<b>Дизлайкнул:</b> <a href=\"{url}\">{track}</a>",
        "no_lyrics": "<b>Текста нет:</b> <a href=\"{url}\">{track}</a>",
        "no_synced_lyrics": "<b>Текста с таймкодами нет:</b> <a href=\"{url}\">{track}</a>",
        "live_lyrics_loading": LOADING_EMOJI,
        "lyrics": "<b>Текст:</b> <a href=\"{url}\">{track}</a>\n\n<pre>{text}</pre>",
        "autobio_enabled": "<b>Autobio включен.</b>",
        "autobio_disabled": "<b>Autobio выключен.</b>",
        "debugging": LOADING_EMOJI,
        "now_listening_label": "Слушается на",
        "playing_from_label": "Источник:",
        "yandex_music_link": "Яндекс Музыка",
    }

    strings_uk = {
        "name": "DragoYAMusic",
        "_cls_doc": "Інструменти Яндекс Музики: поточний трек, банер, аудіо, лайки, текст і autobio.",
        "guide": (
            "<b>DragoYAMusic by @firedragoq</b>\n\n"
            "<code>.dt TOKEN</code> / <code>.dyatoken</code> - зберегти OAuth-токен\n"
            "<code>.ds</code> / <code>.dyas</code> - перевірити токен\n"
            "<code>.dn</code> / <code>.dyan</code> - поточний трек з банером\n"
            "<code>.da</code> / <code>.dyat</code> - надіслати поточний трек аудіо\n"
            "<code>.dq запит</code> / <code>.dyaq</code> - знайти й надіслати трек\n"
            "<code>.dl</code> / <code>.dyalike</code> - лайкнути трек\n"
            "<code>.du</code> / <code>.dyaunlike</code> - прибрати лайк\n"
            "<code>.dd</code> / <code>.dyadislike</code> - дизлайкнути трек\n"
            "<code>.dr</code> / <code>.dyalyr</code> - текст поточного треку\n"
            "<code>.dv</code> / <code>.dyalive</code> - живий текст за таймкодами\n"
            "<code>.db</code> / <code>.dyab</code> - увімкнути/вимкнути autobio\n"
            "<code>.dk</code> / <code>.dyalink</code> - посилання на поточний трек\n"
            "<code>.dm</code> / <code>.dyad</code> - безпечна діагностика\n"
            "<code>.dg</code> / <code>.dyag</code> - цей гайд\n\n"
            "Гайд по токену: "
            "<a href=\"https://yandex-music.readthedocs.io/en/main/token.html\">"
            "yandex-music.readthedocs.io</a>"
        ),
        "no_token": "<b>Спочатку вкажи токен Яндекс Музики:</b> <code>.dyatoken TOKEN</code>",
        "bad_token": "<b>Не вдалося увійти в Яндекс Музику. Перевір токен.</b>",
        "saved": "<b>Токен збережено.</b>",
        "checking": LOADING_EMOJI,
        "connected": "<b>Яндекс Музика підключена.</b>",
        "loading": LOADING_EMOJI,
        "not_playing": "<b>Зараз ти нічого не слухаєш.</b>",
        "paused": "<b>Яндекс Музика на паузі.</b>",
        "uploading_banner": LOADING_EMOJI,
        "downloading_track": LOADING_EMOJI,
        "no_query": "<b>Напиши пошуковий запит.</b>",
        "not_found": "<b>Нічого не знайдено.</b>",
        "download_error": "<b>Не вдалося завантажити цей трек.</b>",
        "liked": "<b>Лайкнув:</b> <a href=\"{url}\">{track}</a>",
        "unliked": "<b>Прибрав лайк:</b> <a href=\"{url}\">{track}</a>",
        "disliked": "<b>Дизлайкнув:</b> <a href=\"{url}\">{track}</a>",
        "no_lyrics": "<b>Тексту немає:</b> <a href=\"{url}\">{track}</a>",
        "no_synced_lyrics": "<b>Тексту з таймкодами немає:</b> <a href=\"{url}\">{track}</a>",
        "live_lyrics_loading": LOADING_EMOJI,
        "lyrics": "<b>Текст:</b> <a href=\"{url}\">{track}</a>\n\n<pre>{text}</pre>",
        "autobio_enabled": "<b>Autobio увімкнено.</b>",
        "autobio_disabled": "<b>Autobio вимкнено.</b>",
        "debugging": LOADING_EMOJI,
        "now_listening_label": "Слухається на",
        "playing_from_label": "Джерело:",
        "yandex_music_link": "Яндекс Музика",
    }

    strings_ua = strings_uk

    strings_de = {
        "name": "DragoYAMusic",
        "_cls_doc": "Yandex Music Werkzeuge: aktueller Track, Banner, Audio, Likes, Lyrics und Autobio.",
        "guide": (
            "<b>DragoYAMusic by @firedragoq</b>\n\n"
            "<code>.dt TOKEN</code> / <code>.dyatoken</code> - OAuth-Token speichern\n"
            "<code>.ds</code> / <code>.dyas</code> - Token prüfen\n"
            "<code>.dn</code> / <code>.dyan</code> - aktueller Track mit Banner\n"
            "<code>.da</code> / <code>.dyat</code> - aktuellen Track als Audio senden\n"
            "<code>.dq query</code> / <code>.dyaq</code> - Track suchen und senden\n"
            "<code>.dl</code> / <code>.dyalike</code> - Track liken\n"
            "<code>.du</code> / <code>.dyaunlike</code> - Like entfernen\n"
            "<code>.dd</code> / <code>.dyadislike</code> - Track disliken\n"
            "<code>.dr</code> / <code>.dyalyr</code> - Lyrics des aktuellen Tracks\n"
            "<code>.dv</code> / <code>.dyalive</code> - Live-Lyrics mit Zeitcodes\n"
            "<code>.db</code> / <code>.dyab</code> - Autobio umschalten\n"
            "<code>.dk</code> / <code>.dyalink</code> - Link zum aktuellen Track\n"
            "<code>.dm</code> / <code>.dyad</code> - sichere Diagnose\n"
            "<code>.dg</code> / <code>.dyag</code> - diese Anleitung\n\n"
            "Token-Anleitung: "
            "<a href=\"https://yandex-music.readthedocs.io/en/main/token.html\">"
            "yandex-music.readthedocs.io</a>"
        ),
        "no_token": "<b>Lege zuerst den Yandex Music Token fest:</b> <code>.dyatoken TOKEN</code>",
        "bad_token": "<b>Anmeldung bei Yandex Music fehlgeschlagen. Prüfe den Token.</b>",
        "saved": "<b>Token gespeichert.</b>",
        "checking": LOADING_EMOJI,
        "connected": "<b>Yandex Music ist verbunden.</b>",
        "loading": LOADING_EMOJI,
        "not_playing": "<b>Du hörst gerade nichts.</b>",
        "paused": "<b>Yandex Music ist pausiert.</b>",
        "uploading_banner": LOADING_EMOJI,
        "downloading_track": LOADING_EMOJI,
        "no_query": "<b>Gib eine Suchanfrage an.</b>",
        "not_found": "<b>Nichts gefunden.</b>",
        "download_error": "<b>Dieser Track konnte nicht heruntergeladen werden.</b>",
        "liked": "<b>Geliked:</b> <a href=\"{url}\">{track}</a>",
        "unliked": "<b>Like entfernt:</b> <a href=\"{url}\">{track}</a>",
        "disliked": "<b>Disliked:</b> <a href=\"{url}\">{track}</a>",
        "no_lyrics": "<b>Keine Lyrics für:</b> <a href=\"{url}\">{track}</a>",
        "no_synced_lyrics": "<b>Keine synchronisierten Lyrics für:</b> <a href=\"{url}\">{track}</a>",
        "live_lyrics_loading": LOADING_EMOJI,
        "lyrics": "<b>Lyrics:</b> <a href=\"{url}\">{track}</a>\n\n<pre>{text}</pre>",
        "autobio_enabled": "<b>Autobio aktiviert.</b>",
        "autobio_disabled": "<b>Autobio deaktiviert.</b>",
        "debugging": LOADING_EMOJI,
        "now_listening_label": "Läuft auf",
        "playing_from_label": "Quelle:",
        "yandex_music_link": "Yandex Music",
    }

    strings_es = {
        "name": "DragoYAMusic",
        "_cls_doc": "Herramientas de Yandex Music: pista actual, banner, audio, likes, letras y autobio.",
        "guide": (
            "<b>DragoYAMusic by @firedragoq</b>\n\n"
            "<code>.dt TOKEN</code> / <code>.dyatoken</code> - guardar token OAuth\n"
            "<code>.ds</code> / <code>.dyas</code> - comprobar token\n"
            "<code>.dn</code> / <code>.dyan</code> - pista actual con banner\n"
            "<code>.da</code> / <code>.dyat</code> - enviar pista actual como audio\n"
            "<code>.dq consulta</code> / <code>.dyaq</code> - buscar y enviar una pista\n"
            "<code>.dl</code> / <code>.dyalike</code> - dar like a la pista\n"
            "<code>.du</code> / <code>.dyaunlike</code> - quitar like\n"
            "<code>.dd</code> / <code>.dyadislike</code> - dar dislike a la pista\n"
            "<code>.dr</code> / <code>.dyalyr</code> - letra de la pista actual\n"
            "<code>.dv</code> / <code>.dyalive</code> - letra en vivo con tiempos\n"
            "<code>.db</code> / <code>.dyab</code> - activar/desactivar autobio\n"
            "<code>.dk</code> / <code>.dyalink</code> - enlace de la pista actual\n"
            "<code>.dm</code> / <code>.dyad</code> - diagnóstico seguro\n"
            "<code>.dg</code> / <code>.dyag</code> - esta guía\n\n"
            "Guía del token: "
            "<a href=\"https://yandex-music.readthedocs.io/en/main/token.html\">"
            "yandex-music.readthedocs.io</a>"
        ),
        "no_token": "<b>Primero configura el token de Yandex Music:</b> <code>.dyatoken TOKEN</code>",
        "bad_token": "<b>No se pudo autorizar en Yandex Music. Revisa el token.</b>",
        "saved": "<b>Token guardado.</b>",
        "checking": LOADING_EMOJI,
        "connected": "<b>Yandex Music está conectado.</b>",
        "loading": LOADING_EMOJI,
        "not_playing": "<b>No estás escuchando nada ahora.</b>",
        "paused": "<b>Yandex Music está en pausa.</b>",
        "uploading_banner": LOADING_EMOJI,
        "downloading_track": LOADING_EMOJI,
        "no_query": "<b>Escribe una consulta de búsqueda.</b>",
        "not_found": "<b>No se encontró nada.</b>",
        "download_error": "<b>No se pudo descargar esta pista.</b>",
        "liked": "<b>Like añadido:</b> <a href=\"{url}\">{track}</a>",
        "unliked": "<b>Like quitado:</b> <a href=\"{url}\">{track}</a>",
        "disliked": "<b>Dislike añadido:</b> <a href=\"{url}\">{track}</a>",
        "no_lyrics": "<b>No hay letra para:</b> <a href=\"{url}\">{track}</a>",
        "no_synced_lyrics": "<b>No hay letra sincronizada para:</b> <a href=\"{url}\">{track}</a>",
        "live_lyrics_loading": LOADING_EMOJI,
        "lyrics": "<b>Letra:</b> <a href=\"{url}\">{track}</a>\n\n<pre>{text}</pre>",
        "autobio_enabled": "<b>Autobio activado.</b>",
        "autobio_disabled": "<b>Autobio desactivado.</b>",
        "debugging": LOADING_EMOJI,
        "now_listening_label": "Sonando en",
        "playing_from_label": "Fuente:",
        "yandex_music_link": "Yandex Music",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "token",
                "",
                "Yandex Music OAuth token",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "now_playing_text",
                self._default_now_playing_text(),
                "HTML template for now playing output",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_track",
                self.TRACK_EMOJI,
                "Premium emoji before artist and title",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_device",
                self.DEVICE_EMOJI,
                "Premium emoji before listening device",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_volume",
                self.VOLUME_EMOJI,
                "Premium emoji before volume",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_from",
                self.FROM_EMOJI,
                "Premium emoji before playing source",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_link",
                self.LINK_EMOJI,
                "Premium emoji before Yandex Music link",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "autobio_text",
                "{performer} - {title}",
                "Autobio text while music is playing",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "no_playing_bio_text",
                "DragoYAMusic by @firedragoq",
                "Autobio text when nothing is playing",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "send_banner",
                True,
                "Attach a generated banner to .dyan",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "show_paused",
                False,
                "Show paused track instead of pause warning",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "queue_fallback",
                True,
                "Use the latest Yandex Music queue when Ynison state is empty",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "blur",
                18,
                "Banner background blur",
                validator=loader.validators.Integer(minimum=0, maximum=60),
            ),
            loader.ConfigValue(
                "timeout",
                12,
                "Network timeout in seconds",
                validator=loader.validators.Integer(minimum=5, maximum=60),
            ),
            loader.ConfigValue(
                "live_lyrics_interval",
                1.0,
                "Live lyrics edit interval in seconds",
                validator=loader.validators.Float(minimum=0.5, maximum=5),
            ),
            loader.ConfigValue(
                "live_lyrics_max_seconds",
                900,
                "Maximum live lyrics session length in seconds",
                validator=loader.validators.Integer(minimum=60, maximum=3600),
            ),
        )

        self._client: Optional[telethon.TelegramClient] = None
        self._db = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._ym_client: Optional[yandex_music.ClientAsync] = None
        self._ym_token: Optional[str] = None
        self._device_id = uuid.uuid4().hex
        self._premium = False

    def _default_now_playing_text(self) -> str:
        return (
            "{emoji_track} <b>{performer} — {title}</b>\n\n"
            "{emoji_device} <b>{now_listening_label} <code>{device}</code> "
            "({emoji_volume} {volume}%)</b>\n"
            "{emoji_from} <b>{playing_from_label}</b> {playing_from}\n\n"
            "{emoji_link} <b>{link}</b>"
        )

    def _migrate_emoji_config(self):
        old_track = {
            "<tg-emoji emoji-id=5350279866304445948>🔥</tg-emoji>",
            "<tg-emoji emoji-id=5350279866304445948>🔥</tg-emoji>",
            "<emoji document_id=5350279866304445948>🔥</emoji>",
        }
        old_device = {
            "<tg-emoji emoji-id=5348421451135336104>👾</tg-emoji>",
            "<tg-emoji emoji-id=6039404727542747508></tg-emoji>",
            "<emoji document_id=5348421451135336104>👾</emoji>",
            "<emoji document_id=6039404727542747508>⌨️</emoji>",
            "⌨️",
        }
        old_volume = {
            "<tg-emoji emoji-id=6039454987250044861></tg-emoji>",
            "<emoji document_id=6039454987250044861></emoji>",
        }
        old_from = {
            "<tg-emoji emoji-id=5350695039318114023>🔗</tg-emoji>",
            "<tg-emoji emoji-id=6039630677182254664></tg-emoji>",
            "<emoji document_id=5350695039318114023>🔗</emoji>",
            "<emoji document_id=6039630677182254664>🗂</emoji>",
        }
        old_link = {
            "<tg-emoji emoji-id=5346296430166293639>📱</tg-emoji>",
            "<emoji document_id=5346296430166293639>📱</emoji>",
        }

        if self.config["emoji_track"] in old_track:
            self.config["emoji_track"] = self.TRACK_EMOJI
        if self.config["emoji_device"] in old_device:
            self.config["emoji_device"] = self.DEVICE_EMOJI
        if self.config["emoji_volume"] in old_volume:
            self.config["emoji_volume"] = self.VOLUME_EMOJI
        if self.config["emoji_from"] in old_from:
            self.config["emoji_from"] = self.FROM_EMOJI
        if self.config["emoji_link"] in old_link:
            self.config["emoji_link"] = self.LINK_EMOJI

        text = str(self.config["now_playing_text"] or "")
        legacy_text = (
            "⌨️ Now is listening" in text
            or "<tg-emoji " in text
            or "<emoji document_id=6039404727542747508" in text
            or "<emoji document_id=6039630677182254664" in text
            or ("Now is listening on" in text and "{emoji_device}" not in text)
            or ("Now is listening on" in text and "{now_listening_label}" not in text)
            or ("Playing from:" in text and "{emoji_from}" not in text)
            or ("Playing from:" in text and "{playing_from_label}" not in text)
        )
        if legacy_text:
            self.config["now_playing_text"] = self._default_now_playing_text()

    async def client_ready(self, client, db):
        self._client = client
        self._db = db
        self._migrate_emoji_config()
        try:
            me = await self._client.get_me()
            self._premium = bool(getattr(me, "premium", False))
        except Exception:
            self._premium = False

        if self.get("autobio", False):
            self.autobio.start()

    async def on_unload(self):
        if self._http and not self._http.closed:
            await self._http.close()

    def _token(self) -> str:
        return str(self.config["token"] or "").strip()

    def _session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            timeout = aiohttp.ClientTimeout(total=float(self.config["timeout"]))
            self._http = aiohttp.ClientSession(timeout=timeout)
        return self._http

    async def _get_ym_client(self) -> Optional[yandex_music.ClientAsync]:
        token = self._token()
        if not token:
            return None

        if self._ym_client is not None and self._ym_token == token:
            return self._ym_client

        try:
            client = await yandex_music.ClientAsync(token).init()
        except Exception as e:
            logger.warning("Yandex Music auth failed: %s", e)
            self._ym_client = None
            self._ym_token = None
            return None

        self._ym_client = client
        self._ym_token = token
        return client

    def _ynison_headers(self, token: str, protocol: Dict[str, str]) -> Dict[str, str]:
        return {
            "Authorization": f"OAuth {token}",
            "Origin": "http://music.yandex.ru",
            "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(protocol)}",
        }

    async def _receive_json(self, ws: aiohttp.ClientWebSocketResponse) -> Dict[str, Any]:
        msg = await ws.receive(timeout=float(self.config["timeout"]))
        if msg.type == aiohttp.WSMsgType.TEXT:
            return json.loads(msg.data)
        if msg.type == aiohttp.WSMsgType.BINARY:
            return json.loads(msg.data.decode("utf-8"))
        raise RuntimeError(f"Unexpected websocket message: {msg.type}")

    def _shadow_state(self) -> Dict[str, Any]:
        stamp = int(time.time() * 1000)
        return {
            "update_full_state": {
                "player_state": {
                    "player_queue": {
                        "current_playable_index": -1,
                        "entity_id": "",
                        "entity_type": "VARIOUS",
                        "playable_list": [],
                        "options": {"repeat_mode": "NONE"},
                        "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                        "version": {
                            "device_id": self._device_id,
                            "version": 9021243204784341000 + stamp,
                            "timestamp_ms": 0,
                        },
                        "from_optional": "",
                    },
                    "status": {
                        "duration_ms": 0,
                        "paused": True,
                        "playback_speed": 1,
                        "progress_ms": 0,
                        "version": {
                            "device_id": self._device_id,
                            "version": 8321822175199937000 + stamp,
                            "timestamp_ms": 0,
                        },
                    },
                },
                "device": {
                    "capabilities": {
                        "can_be_player": True,
                        "can_be_remote_controller": False,
                        "volume_granularity": 16,
                    },
                    "info": {
                        "device_id": self._device_id,
                        "type": "WEB",
                        "title": "Chrome Browser",
                        "app_name": "Chrome",
                    },
                    "volume_info": {"volume": 0},
                    "is_shadow": True,
                },
                "is_currently_active": False,
            },
            "rid": str(uuid.uuid4()),
            "player_action_timestamp_ms": 0,
            "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
        }

    async def _ynison_state(self) -> Dict[str, Any]:
        token = self._token()
        protocol = {
            "Ynison-Device-Id": self._device_id,
            "Ynison-Device-Info": json.dumps({"app_name": "Chrome", "type": 1}),
        }

        session = self._session()
        async with session.ws_connect(
            REDIRECTOR_URL,
            headers=self._ynison_headers(token, protocol),
            timeout=float(self.config["timeout"]),
        ) as ws:
            redirect = await self._receive_json(ws)

        protocol["Ynison-Redirect-Ticket"] = redirect["redirect_ticket"]
        state_url = f"wss://{redirect['host']}{STATE_PATH}"

        async with session.ws_connect(
            state_url,
            headers=self._ynison_headers(token, protocol),
            timeout=float(self.config["timeout"]),
        ) as ws:
            await ws.send_str(json.dumps(self._shadow_state(), separators=(",", ":")))
            return await self._receive_json(ws)

    def _track_artists(self, track: Any) -> List[str]:
        try:
            return list(track.artists_name())
        except Exception:
            return [artist.name for artist in getattr(track, "artists", []) if getattr(artist, "name", None)]

    def _track_id(self, track: Any) -> str:
        return str(getattr(track, "id", None) or getattr(track, "real_id", None) or "")

    def _api_track_id(self, track: Any) -> str:
        return str(getattr(track, "track_id", None) or self._track_id(track))

    def _album(self, track: Any) -> Optional[Any]:
        albums = getattr(track, "albums", None) or []
        return albums[0] if albums else None

    def _track_url(self, track: Any) -> str:
        track_id = self._track_id(track)
        album = self._album(track)
        album_id = getattr(album, "id", None)
        if album_id:
            return f"https://music.yandex.ru/album/{album_id}/track/{track_id}"
        return f"https://music.yandex.ru/track/{track_id}"

    def _cover_url(self, track: Any, size: str = "1000x1000") -> Optional[str]:
        cover_uri = getattr(track, "cover_uri", None)
        if not cover_uri:
            album = self._album(track)
            cover_uri = getattr(album, "cover_uri", None) if album else None
        if not cover_uri:
            return None
        return f"https://{cover_uri.replace('%%', size)}"

    def _track_from_track_id(self, track_id: Any) -> str:
        for attr in ("track_id", "id", "real_id"):
            value = getattr(track_id, attr, None)
            if value:
                return str(value)
        return str(track_id)

    def _device_details(self, state: Dict[str, Any]) -> Tuple[str, str]:
        active_id = state.get("active_device_id_optional")
        devices = state.get("devices") or []
        for device in devices:
            info = device.get("info") or {}
            if info.get("device_id") != active_id:
                continue
            title = info.get("title") or info.get("app_name") or "Unknown"
            volume_info = device.get("volume_info") or {}
            volume = device.get("volume", volume_info.get("volume"))
            if isinstance(volume, (int, float)):
                if volume <= 1:
                    volume = round(volume * 100)
                else:
                    volume = round(volume)
                return title, str(volume)
            return title, "?"
        return "Unknown", "?"

    def _format_time(self, ms: int) -> str:
        seconds = max(0, int(ms // 1000))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _genre(self, track: Any) -> str:
        album = self._album(track)
        raw = getattr(album, "genre", None) if album else None
        mapping = {
            "rusrap": "Русский рэп",
            "pop": "Поп",
            "rock": "Рок",
            "alternative": "Альтернатива",
            "electronics": "Электроника",
            "hip-hop": "Хип-хоп",
            "rap": "Рэп",
            "rnb": "R&B",
            "metal": "Метал",
            "indie": "Инди",
            "folk": "Фолк",
            "soundtrack": "Саундтрек",
        }
        if not raw:
            return "Music"
        return mapping.get(str(raw), str(raw).capitalize())

    def _build_now(
        self,
        track: Any,
        *,
        duration_ms: Optional[int] = None,
        progress_ms: int = 0,
        paused: bool = False,
        device: str = "Unknown",
        volume: str = "?",
        entity_type: str = "VARIOUS",
        entity_id: str = "",
        repeat_mode: str = "NONE",
        source: str = "ynison",
    ) -> Dict[str, Any]:
        album = self._album(track)
        artists = self._track_artists(track)
        duration = int(duration_ms or getattr(track, "duration_ms", 0) or 0)
        progress = int(progress_ms or 0)
        year = getattr(album, "year", None) if album else None
        genre = self._genre(track)

        return {
            "track_object": track,
            "track_id": self._api_track_id(track),
            "real_track_id": self._track_id(track),
            "title": getattr(track, "title", "Unknown"),
            "artist": ", ".join(artists) if artists else "Unknown",
            "artists": artists or ["Unknown"],
            "album": getattr(album, "title", "Single") if album else "Single",
            "album_id": getattr(album, "id", 0) if album else 0,
            "duration_ms": duration,
            "progress_ms": min(progress, duration) if duration else progress,
            "paused": paused,
            "device": device,
            "volume": volume,
            "entity_type": entity_type or "VARIOUS",
            "entity_id": str(entity_id or ""),
            "repeat_mode": repeat_mode or "NONE",
            "source": source,
            "genre": genre,
            "year": str(year) if year else "",
            "url": self._track_url(track),
            "cover_url": self._cover_url(track),
        }

    async def _now_from_ynison(self, ym_client: yandex_music.ClientAsync) -> Optional[Dict[str, Any]]:
        state = await self._ynison_state()
        player = state.get("player_state") or {}
        queue = player.get("player_queue") or {}
        status = player.get("status") or {}
        items = queue.get("playable_list") or []
        index = int(queue.get("current_playable_index", -1))

        if index < 0 or index >= len(items):
            return None

        current = items[index]
        if current.get("playable_type") == "LOCAL_TRACK":
            return None

        playable_id = current.get("playable_id")
        if not playable_id:
            return None

        tracks = await ym_client.tracks(playable_id)
        if not tracks:
            return None

        device, volume = self._device_details(state)
        return self._build_now(
            tracks[0],
            duration_ms=int(status.get("duration_ms") or 0),
            progress_ms=int(status.get("progress_ms") or 0),
            paused=bool(status.get("paused", True)),
            device=device,
            volume=volume,
            entity_type=queue.get("entity_type", "VARIOUS"),
            entity_id=queue.get("entity_id", ""),
            repeat_mode=(queue.get("options") or {}).get("repeat_mode", "NONE"),
            source="ynison",
        )

    async def _now_from_queue(self, ym_client: yandex_music.ClientAsync) -> Optional[Dict[str, Any]]:
        queues = await ym_client.queues_list()
        if not queues:
            return None

        queue_item = queues[0]
        queue = None
        queue_id = getattr(queue_item, "id", None)

        if queue_id and hasattr(ym_client, "queue"):
            queue = await ym_client.queue(queue_id)
        if queue is None and hasattr(queue_item, "fetch_queue_async"):
            queue = await queue_item.fetch_queue_async()
        if queue is None:
            return None

        current = queue.get_current_track() if hasattr(queue, "get_current_track") else None
        if current is None:
            return None

        if hasattr(current, "fetch_track_async"):
            track = await current.fetch_track_async()
        else:
            tracks = await ym_client.tracks(self._track_from_track_id(current))
            track = tracks[0] if tracks else None

        if track is None:
            return None

        return self._build_now(
            track,
            paused=False,
            device="Latest queue",
            volume="?",
            source="queue",
        )

    async def _now_playing(self) -> Optional[Dict[str, Any]]:
        ym_client = await self._get_ym_client()
        if ym_client is None:
            raise RuntimeError("Yandex Music client is not available")

        try:
            now = await self._now_from_ynison(ym_client)
            if now:
                return now
        except Exception as e:
            logger.debug("Ynison lookup failed: %s", e)

        if self.config["queue_fallback"]:
            try:
                return await self._now_from_queue(ym_client)
            except Exception as e:
                logger.debug("Queue fallback failed: %s", e)

        return None

    async def _download_bytes(self, url: Optional[str]) -> Optional[bytes]:
        if not url:
            return None
        try:
            async with self._session().get(url) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except Exception as e:
            logger.debug("Download failed: %s", e)
            return None

    async def _lyrics_text(self, ym_client: yandex_music.ClientAsync, track_id: str, fmt: str = "TEXT") -> str:
        try:
            lyrics = await ym_client.tracks_lyrics(track_id, format_=fmt)
        except TypeError:
            try:
                lyrics = await ym_client.tracks_lyrics(track_id, fmt)
            except TypeError:
                lyrics = await ym_client.tracks_lyrics(track_id)

        if not lyrics:
            return ""

        if hasattr(lyrics, "fetch_lyrics_async"):
            try:
                text = await lyrics.fetch_lyrics_async()
                if text:
                    return str(text).strip()
            except Exception as e:
                logger.debug("Lyrics fetch helper failed: %s", e)

        data = await self._download_bytes(getattr(lyrics, "download_url", None))
        return data.decode("utf-8", errors="ignore").strip() if data else ""

    def _parse_lrc(self, text: str) -> List[Tuple[int, str]]:
        stamp_re = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
        entries: List[Tuple[int, str]] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            stamps = list(stamp_re.finditer(line))
            if not stamps:
                continue

            lyric = stamp_re.sub("", line).strip()
            if not lyric:
                continue

            for stamp in stamps:
                minutes = int(stamp.group(1))
                seconds = int(stamp.group(2))
                fraction = stamp.group(3) or "0"
                if len(fraction) == 1:
                    millis = int(fraction) * 100
                elif len(fraction) == 2:
                    millis = int(fraction) * 10
                else:
                    millis = int(fraction[:3])
                entries.append((((minutes * 60) + seconds) * 1000 + millis, lyric))

        entries.sort(key=lambda item: item[0])

        deduped: List[Tuple[int, str]] = []
        for stamp, lyric in entries:
            if deduped and deduped[-1][0] == stamp:
                deduped[-1] = (stamp, lyric)
            else:
                deduped.append((stamp, lyric))
        return deduped

    def _lyric_window(self, entries: List[Tuple[int, str]], progress_ms: int) -> Tuple[str, str, str]:
        if not entries:
            return "", "", ""

        index = 0
        edge = max(0, int(progress_ms)) + 350
        for i, (stamp, _) in enumerate(entries):
            if stamp <= edge:
                index = i
            else:
                break

        previous = entries[index - 1][1] if index > 0 else ""
        current = entries[index][1]
        next_line = entries[index + 1][1] if index + 1 < len(entries) else ""
        return previous, current, next_line

    def _render_live_lyrics(
        self,
        now: Dict[str, Any],
        previous: str,
        current: str,
        next_line: str,
        progress_ms: int,
    ) -> str:
        header = html.escape(f"{now['artist']} - {now['title']}")
        progress = self._format_time(progress_ms)
        duration = self._format_time(now["duration_ms"])
        rows = [
            f"<i>{html.escape(previous) if previous else ' '}</i>",
            f"<b>{html.escape(current) if current else '...'}</b>",
            f"<i>{html.escape(next_line) if next_line else ' '}</i>",
        ]
        return (
            f"{self.config['emoji_track']} <b>{header}</b>\n"
            f"<code>{progress} / {duration}</code>\n\n"
            + "\n".join(rows)
        )

    async def _download_track(self, ym_client: yandex_music.ClientAsync, track_id: str) -> Optional[io.BytesIO]:
        try:
            variants = await ym_client.tracks_download_info(track_id, get_direct_links=True)
            if not variants:
                return None
            best = max(variants, key=lambda item: getattr(item, "bitrate_in_kbps", 0) or 0)
            audio = io.BytesIO(await best.download_bytes_async())
            audio.name = "yamusic.mp3"
            return audio
        except Exception as e:
            logger.warning("Track download failed: %s", e)
            return None

    def _safe_track_name(self, now: Dict[str, Any]) -> str:
        name = f"{now['artist']} - {now['title']}"
        name = "".join(ch for ch in name if ch not in r'\/:*?"<>|').strip()
        return (name[:90] or "track") + ".mp3"

    async def _render_banner(self, now: Dict[str, Any]) -> io.BytesIO:
        cover = await self._download_bytes(now["cover_url"]) or b""
        meta_parts = []
        if now["year"]:
            meta_parts.append(now["year"])
        meta_parts.append(now["genre"])
        if now["repeat_mode"] != "NONE":
            meta_parts.append(f"Repeat {now['repeat_mode'].lower()}")
        meta = " / ".join(meta_parts)

        banner = FiredBanner(
            title=now["title"],
            artist=now["artist"],
            album=now["album"],
            duration_ms=now["duration_ms"],
            progress_ms=now["progress_ms"],
            cover_bytes=cover,
            device=now["device"],
            meta=meta,
            paused=now["paused"],
            blur=int(self.config["blur"]),
        )
        return await utils.run_sync(banner.render)

    async def _playing_from(self, ym_client: yandex_music.ClientAsync, now: Dict[str, Any]) -> str:
        entity_type = now["entity_type"]
        entity_id = now["entity_id"]

        try:
            if entity_type == "PLAYLIST" and entity_id:
                playlist = (await ym_client.playlists_list(entity_id))[0]
                title = html.escape(getattr(playlist, "title", "Playlist"))
                owner = getattr(getattr(playlist, "owner", None), "login", "")
                kind = getattr(playlist, "kind", entity_id)
                if owner:
                    return f'<a href="https://music.yandex.ru/users/{owner}/playlists/{kind}">{title}</a>'
                return title
            if entity_type == "ALBUM" and entity_id:
                album = (await ym_client.albums(entity_id))[0]
                title = html.escape(getattr(album, "title", "Album"))
                return f'<a href="https://music.yandex.ru/album/{getattr(album, "id", entity_id)}">{title}</a>'
            if entity_type == "ARTIST" and entity_id:
                artist = (await ym_client.artists(entity_id))[0]
                name = html.escape(getattr(artist, "name", "Artist"))
                return f'<a href="https://music.yandex.ru/artist/{getattr(artist, "id", entity_id)}">{name}</a>'
        except Exception:
            pass

        mapping = {
            "PLAYLIST": "playlist",
            "ALBUM": "album",
            "ARTIST": "artist",
            "VARIOUS": "recommendations",
            "RADIO": "radio",
        }
        return mapping.get(entity_type, entity_type.lower() if entity_type else "unknown")

    async def _render_text(self, now: Dict[str, Any]) -> str:
        ym_client = await self._get_ym_client()
        playing_from = await self._playing_from(ym_client, now) if ym_client else "unknown"
        link_label = html.escape(self.strings("yandex_music_link"))
        link = f'<a href="{html.escape(now["url"], quote=True)}">{link_label}</a>'
        values = {
            "performer": html.escape(now["artist"]),
            "artist": html.escape(now["artist"]),
            "title": html.escape(now["title"]),
            "album": html.escape(now["album"]),
            "album_id": html.escape(str(now["album_id"])),
            "track_id": html.escape(str(now["track_id"])),
            "duration": self._format_time(now["duration_ms"]),
            "progress": self._format_time(now["progress_ms"]),
            "device": html.escape(now["device"]),
            "volume": html.escape(str(now["volume"])),
            "playing_from": playing_from,
            "source": html.escape(now["source"]),
            "link": link,
            "yandex_link": link,
            "url": html.escape(now["url"], quote=True),
            "emoji_track": self.config["emoji_track"],
            "emoji_device": self.config["emoji_device"],
            "emoji_volume": self.config["emoji_volume"],
            "emoji_from": self.config["emoji_from"],
            "emoji_link": self.config["emoji_link"],
            "now_listening_label": html.escape(self.strings("now_listening_label")),
            "playing_from_label": html.escape(self.strings("playing_from_label")),
            "yandex_music_link": link_label,
        }
        try:
            return self.config["now_playing_text"].format(**values)
        except Exception:
            logger.exception("Invalid now_playing_text template")
            return (
                f"{values['emoji_track']} <b>{values['performer']} — {values['title']}</b>\n"
                f"{values['progress']} / {values['duration']}\n\n{link}"
            )

    def _track_title(self, now: Dict[str, Any]) -> str:
        return html.escape(f"{now['artist']} - {now['title']}")

    async def _current_or_answer(self, message: telethon.types.Message) -> Optional[Dict[str, Any]]:
        if not self._token():
            await utils.answer(message, self.strings("no_token"))
            return None
        try:
            now = await self._now_playing()
        except Exception as e:
            logger.warning("Now playing lookup failed: %s", e)
            await utils.answer(message, self.strings("bad_token"))
            return None
        if not now:
            await utils.answer(message, self.strings("not_playing"))
            return None
        if now["paused"] and not self.config["show_paused"]:
            await utils.answer(message, self.strings("paused"))
            return None
        return now

    async def _now_play_placeholder(self):
        try:
            now = await self._now_playing()
            if not now or now["paused"]:
                return "Not playing"
            return f"{now['artist']} - {now['title']}"
        except Exception:
            return "Not playing"

    async def _duration_placeholder(self):
        try:
            now = await self._now_playing()
            if not now or now["paused"]:
                return "0:00 / 0:00"
            return f"{self._format_time(now['progress_ms'])} / {self._format_time(now['duration_ms'])}"
        except Exception:
            return "0:00 / 0:00"

    @loader.loop(1800, autostart=True)
    async def premium_check(self):
        if not self._client:
            return
        try:
            me = await self._client.get_me()
            self._premium = bool(getattr(me, "premium", False))
        except Exception:
            pass

    @loader.loop(15)
    async def autobio(self):
        if not self._token():
            self.set("autobio", False)
            self.autobio.stop()
            return

        try:
            now = await self._now_playing()
            if now and not now["paused"]:
                text = self.config["autobio_text"].format(
                    performer=now["artist"],
                    artist=now["artist"],
                    title=now["title"],
                    album=now["album"],
                )
            else:
                text = self.config["no_playing_bio_text"]

            await self._client(
                telethon.functions.account.UpdateProfileRequest(
                    about=text[: (140 if self._premium else 70)]
                )
            )
        except telethon.errors.rpcerrorlist.FloodWaitError as e:
            await asyncio.sleep(max(e.seconds, 60))
        except Exception as e:
            logger.debug("Autobio update failed: %s", e)

    @loader.command(
        ru_doc="Гайд и список команд Яндекс Музыки",
        uk_doc="Гайд і список команд Яндекс Музики",
        de_doc="Anleitung und Befehlsliste für Yandex Music",
        es_doc="Guía y lista de comandos de Yandex Music",
        alias="dyag",
    )
    async def dgcmd(self, message: telethon.types.Message):
        """Show token guide and command list."""
        await utils.answer(message, self.strings("guide"))

    @loader.command(
        ru_doc="Сохранить OAuth-токен Яндекс Музыки",
        uk_doc="Зберегти OAuth-токен Яндекс Музики",
        de_doc="OAuth-Token für Yandex Music speichern",
        es_doc="Guardar token OAuth de Yandex Music",
        alias="dyatoken",
    )
    async def dtcmd(self, message: telethon.types.Message):
        """<token> - save Yandex Music OAuth token."""
        token = utils.get_args_raw(message).strip()
        if not token:
            return await utils.answer(message, self.strings("no_token"))

        self.config["token"] = token
        self._ym_client = None
        self._ym_token = None
        await utils.answer(message, self.strings("saved"))

    @loader.command(
        ru_doc="Проверить подключение к Яндекс Музыке",
        uk_doc="Перевірити підключення до Яндекс Музики",
        de_doc="Verbindung zu Yandex Music prüfen",
        es_doc="Comprobar conexión con Yandex Music",
        alias="dyas",
    )
    async def dscmd(self, message: telethon.types.Message):
        """Check Yandex Music token."""
        if not self._token():
            return await utils.answer(message, self.strings("no_token"))
        await utils.answer(message, self.strings("checking"))
        client = await self._get_ym_client()
        await utils.answer(message, self.strings("connected") if client else self.strings("bad_token"))

    @loader.command(
        ru_doc="Включить/выключить autobio",
        uk_doc="Увімкнути/вимкнути autobio",
        de_doc="Autobio umschalten",
        es_doc="Activar/desactivar autobio",
        alias="dyab",
    )
    async def dbcmd(self, message: telethon.types.Message):
        """Toggle autobio with currently playing track."""
        if not self._token():
            return await utils.answer(message, self.strings("no_token"))
        client = await self._get_ym_client()
        if not client:
            return await utils.answer(message, self.strings("bad_token"))

        enabled = not self.get("autobio", False)
        self.set("autobio", enabled)
        if enabled:
            await self.autobio.func(self)
            self.autobio.start()
        else:
            self.autobio.stop()
            try:
                await self._client(
                    telethon.functions.account.UpdateProfileRequest(
                        about=self.config["no_playing_bio_text"][: (140 if self._premium else 70)]
                    )
                )
            except Exception:
                pass
        await utils.answer(message, self.strings("autobio_enabled" if enabled else "autobio_disabled"))

    @loader.command(
        ru_doc="Отправить текущий трек с баннером",
        uk_doc="Надіслати поточний трек з банером",
        de_doc="Aktuellen Track mit Banner senden",
        es_doc="Enviar pista actual con banner",
        alias="dyan",
    )
    async def dncmd(self, message: telethon.types.Message):
        """Send current Yandex Music track with banner."""
        await utils.answer(message, self.strings("loading"))
        now = await self._current_or_answer(message)
        if not now:
            return

        text = await self._render_text(now)
        if not self.config["send_banner"]:
            return await utils.answer(message, text)

        # сразу рендерим баннер и отправляем одним финальным сообщением,
        # без промежуточного показа текста (чтобы не мигало)
        banner = await self._render_banner(now)
        await utils.answer(message=message, response=text, file=banner)

    @loader.command(
        ru_doc="Отправить ссылку на текущий трек",
        uk_doc="Надіслати посилання на поточний трек",
        de_doc="Link zum aktuellen Track senden",
        es_doc="Enviar enlace de la pista actual",
        alias="dyalink",
    )
    async def dkcmd(self, message: telethon.types.Message):
        """Send current Yandex Music track link."""
        now = await self._current_or_answer(message)
        if not now:
            return
        await utils.answer(
            message,
            f'<a href="{html.escape(now["url"], quote=True)}">{self._track_title(now)}</a>',
        )

    @loader.command(
        ru_doc="Отправить текущий трек аудиофайлом",
        uk_doc="Надіслати поточний трек аудіофайлом",
        de_doc="Aktuellen Track als Audiodatei senden",
        es_doc="Enviar pista actual como archivo de audio",
        alias="dyat",
    )
    async def dacmd(self, message: telethon.types.Message):
        """Send current Yandex Music track as audio."""
        await utils.answer(message, self.strings("downloading_track"))
        now = await self._current_or_answer(message)
        if not now:
            return

        ym_client = await self._get_ym_client()
        audio = await self._download_track(ym_client, now["track_id"]) if ym_client else None
        if not audio:
            return await utils.answer(message, self.strings("download_error"))
        audio.name = self._safe_track_name(now)

        await utils.answer(
            message=message,
            response=await self._render_text(now),
            file=audio,
            attributes=[
                telethon.types.DocumentAttributeAudio(
                    duration=int(now["duration_ms"] / 1000),
                    title=now["title"],
                    performer=now["artist"],
                )
            ],
        )

    @loader.command(
        ru_doc="Поиск трека в Яндекс Музыке",
        uk_doc="Пошук треку в Яндекс Музиці",
        de_doc="Track in Yandex Music suchen",
        es_doc="Buscar pista en Yandex Music",
        alias="dyaq",
    )
    async def dqcmd(self, message: telethon.types.Message):
        """<query> - search Yandex Music and send first track."""
        if not self._token():
            return await utils.answer(message, self.strings("no_token"))

        query = utils.get_args_raw(message).strip()
        if not query:
            return await utils.answer(message, self.strings("no_query"))

        ym_client = await self._get_ym_client()
        if not ym_client:
            return await utils.answer(message, self.strings("bad_token"))

        search = await ym_client.search(query, type_="track")
        if not getattr(search, "tracks", None) or not search.tracks.results:
            return await utils.answer(message, self.strings("not_found"))

        track = search.tracks.results[0]
        now = self._build_now(track, paused=False, device="Search", volume="?")
        await utils.answer(message, (await self._render_text(now)) + "\n\n" + self.strings("downloading_track"))

        audio = await self._download_track(ym_client, now["track_id"])
        if not audio:
            return await utils.answer(message, self.strings("download_error"))
        audio.name = self._safe_track_name(now)

        await utils.answer(
            message=message,
            response=await self._render_text(now),
            file=audio,
            attributes=[
                telethon.types.DocumentAttributeAudio(
                    duration=int(now["duration_ms"] / 1000),
                    title=now["title"],
                    performer=now["artist"],
                )
            ],
        )

    @loader.command(
        ru_doc="Лайкнуть текущий трек",
        uk_doc="Лайкнути поточний трек",
        de_doc="Aktuellen Track liken",
        es_doc="Dar like a la pista actual",
        alias="dyalike",
    )
    async def dlcmd(self, message: telethon.types.Message):
        """Like current Yandex Music track."""
        now = await self._current_or_answer(message)
        if not now:
            return
        ym_client = await self._get_ym_client()
        await ym_client.users_likes_tracks_add(now["track_id"])
        await utils.answer(
            message,
            self.strings("liked").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
        )

    @loader.command(
        ru_doc="Убрать лайк с текущего трека",
        uk_doc="Прибрати лайк з поточного треку",
        de_doc="Like vom aktuellen Track entfernen",
        es_doc="Quitar like de la pista actual",
        alias="dyaunlike",
    )
    async def ducmd(self, message: telethon.types.Message):
        """Unlike current Yandex Music track."""
        now = await self._current_or_answer(message)
        if not now:
            return
        ym_client = await self._get_ym_client()
        await ym_client.users_likes_tracks_remove(now["track_id"])
        await utils.answer(
            message,
            self.strings("unliked").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
        )

    @loader.command(
        ru_doc="Дизлайкнуть текущий трек",
        uk_doc="Дизлайкнути поточний трек",
        de_doc="Aktuellen Track disliken",
        es_doc="Dar dislike a la pista actual",
        alias="dyadislike",
    )
    async def ddcmd(self, message: telethon.types.Message):
        """Dislike current Yandex Music track."""
        now = await self._current_or_answer(message)
        if not now:
            return
        ym_client = await self._get_ym_client()
        await ym_client.users_dislikes_tracks_add(now["track_id"])
        await utils.answer(
            message,
            self.strings("disliked").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
        )

    @loader.command(
        ru_doc="Живой текст текущего трека",
        uk_doc="Живий текст поточного треку",
        de_doc="Live-Lyrics des aktuellen Tracks",
        es_doc="Letra en vivo de la pista actual",
        alias="dyalive",
    )
    async def dvcmd(self, message: telethon.types.Message):
        """Show synced lyrics in a live three-line view."""
        now = await self._current_or_answer(message)
        if not now:
            return

        ym_client = await self._get_ym_client()
        if not ym_client:
            return await utils.answer(message, self.strings("bad_token"))

        answer = await utils.answer(message, self.strings("live_lyrics_loading"))
        if isinstance(answer, list):
            message = answer[0] if answer else message
        elif answer:
            message = answer

        try:
            text = await self._lyrics_text(ym_client, now["track_id"], "LRC")
        except yandex_music.exceptions.NotFoundError:
            return await utils.answer(
                message,
                self.strings("no_synced_lyrics").format(
                    url=html.escape(now["url"], quote=True),
                    track=self._track_title(now),
                ),
            )
        except Exception as e:
            logger.warning("Synced lyrics lookup failed: %s", e)
            return await utils.answer(
                message,
                self.strings("no_synced_lyrics").format(
                    url=html.escape(now["url"], quote=True),
                    track=self._track_title(now),
                ),
            )

        entries = self._parse_lrc(text)
        if not entries:
            return await utils.answer(
                message,
                self.strings("no_synced_lyrics").format(
                    url=html.escape(now["url"], quote=True),
                    track=self._track_title(now),
                ),
            )

        interval = max(0.5, float(self.config["live_lyrics_interval"]))
        max_seconds = max(interval, int(self.config["live_lyrics_max_seconds"]))
        track_id = now["track_id"]
        base_progress = int(now["progress_ms"])
        base_time = time.monotonic()
        session_started = base_time
        last_sync = base_time
        last_rendered = ""

        while time.monotonic() - session_started <= max_seconds:
            paused = bool(now["paused"])
            progress_ms = base_progress if paused else base_progress + int((time.monotonic() - base_time) * 1000)
            if now["duration_ms"]:
                progress_ms = min(progress_ms, int(now["duration_ms"]))

            previous, current, next_line = self._lyric_window(entries, progress_ms)
            rendered = self._render_live_lyrics(now, previous, current, next_line, progress_ms)

            if rendered != last_rendered:
                try:
                    answer = await utils.answer(message, rendered)
                    if isinstance(answer, list):
                        message = answer[0] if answer else message
                    elif answer:
                        message = answer
                    last_rendered = rendered
                except telethon.errors.rpcerrorlist.FloodWaitError as e:
                    await asyncio.sleep(max(int(e.seconds), interval))
                except telethon.errors.rpcerrorlist.MessageNotModifiedError:
                    pass

            if now["duration_ms"] and progress_ms >= int(now["duration_ms"]):
                break

            await asyncio.sleep(interval)

            if time.monotonic() - last_sync >= 8:
                last_sync = time.monotonic()
                try:
                    fresh = await self._now_playing()
                except Exception as e:
                    logger.debug("Live lyrics resync failed: %s", e)
                    fresh = None

                if not fresh or fresh["track_id"] != track_id:
                    break
                if fresh["paused"] and not self.config["show_paused"]:
                    break

                now = fresh
                base_progress = int(now["progress_ms"])
                base_time = time.monotonic()

    @loader.command(
        ru_doc="Получить текст текущего трека",
        uk_doc="Отримати текст поточного треку",
        de_doc="Lyrics des aktuellen Tracks abrufen",
        es_doc="Obtener letra de la pista actual",
        alias="dyalyr",
    )
    async def drcmd(self, message: telethon.types.Message):
        """Get current Yandex Music track lyrics."""
        now = await self._current_or_answer(message)
        if not now:
            return
        ym_client = await self._get_ym_client()
        try:
            text = await self._lyrics_text(ym_client, now["track_id"], "TEXT")
        except yandex_music.exceptions.NotFoundError:
            return await utils.answer(
                message,
                self.strings("no_lyrics").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
            )
        except Exception as e:
            logger.warning("Lyrics lookup failed: %s", e)
            return await utils.answer(
                message,
                self.strings("no_lyrics").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
            )

        if not text:
            return await utils.answer(
                message,
                self.strings("no_lyrics").format(url=html.escape(now["url"], quote=True), track=self._track_title(now)),
            )

        await utils.answer(
            message,
            self.strings("lyrics").format(
                url=html.escape(now["url"], quote=True),
                track=self._track_title(now),
                text=html.escape(text[:3500]),
            ),
        )

    def _ynison_debug_text(self, state: Dict[str, Any]) -> str:
        player = state.get("player_state") or {}
        queue = player.get("player_queue") or {}
        status = player.get("status") or {}
        items = queue.get("playable_list") or []
        active = state.get("active_device_id_optional") or "None"
        devices = state.get("devices") or []
        index = queue.get("current_playable_index", -1)

        current = None
        if isinstance(index, int) and 0 <= index < len(items):
            current = items[index]

        device_titles = []
        for device in devices[:8]:
            info = device.get("info") or {}
            title = info.get("title") or info.get("app_name") or "Unknown"
            marker = "*" if info.get("device_id") == active else "-"
            device_titles.append(f"{marker} {title}")

        return (
            "<b>DragoYAMusic debug</b>\n"
            f"<b>active_device:</b> <code>{html.escape(str(active))}</code>\n"
            f"<b>devices:</b> <code>{len(devices)}</code>\n"
            f"<b>queue_index:</b> <code>{html.escape(str(index))}</code>\n"
            f"<b>queue_items:</b> <code>{len(items)}</code>\n"
            f"<b>paused:</b> <code>{html.escape(str(status.get('paused')))}</code>\n"
            f"<b>current:</b> <code>{html.escape(json.dumps(current, ensure_ascii=False)[:600])}</code>\n"
            f"<b>device_titles:</b>\n<code>{html.escape(chr(10).join(device_titles) or 'None')}</code>"
        )

    @loader.command(
        ru_doc="Безопасная диагностика состояния плеера",
        uk_doc="Безпечна діагностика стану плеєра",
        de_doc="Sichere Diagnose des Playerstatus",
        es_doc="Diagnóstico seguro del estado del reproductor",
        alias="dyad",
    )
    async def dmcmd(self, message: telethon.types.Message):
        """Show safe player diagnostics without token."""
        if not self._token():
            return await utils.answer(message, self.strings("no_token"))
        await utils.answer(message, self.strings("debugging"))

        try:
            state = await self._ynison_state()
            text = self._ynison_debug_text(state)
        except Exception as e:
            text = f"<b>Ynison error:</b> <code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>"

        try:
            client = await self._get_ym_client()
            queues = await client.queues_list() if client else []
            text += f"\n<b>queue_fallback_items:</b> <code>{len(queues)}</code>"
            if queues:
                text += f"\n<b>latest_queue_id:</b> <code>{html.escape(str(getattr(queues[0], 'id', 'None')))}</code>"
        except Exception as e:
            text += f"\n<b>queue_fallback_error:</b> <code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>"

        await utils.answer(message, text)
