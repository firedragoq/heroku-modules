__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Развлечения
# scope: heroku_only
# requires: Pillow aiohttp
# changelog: первый релиз — .meme (верх|низ) и .dem (демотиватор) по реплаю на картинку

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoMeme — мем-текст и демотиваторы из картинок по реплаю.  ║
# ║  .meme верх|низ  ·  .dem заголовок;подпись                    ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import os

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .. import loader, utils

logger = logging.getLogger(__name__)

# системные шрифты с кириллицей; если нет — качаем DejaVu с jsDelivr и кешируем
_SYS_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_FONT_URL = "https://cdn.jsdelivr.net/npm/dejavu-fonts-ttf@2.37.3/ttf/DejaVuSans-Bold.ttf"
_FONT_BYTES: bytes | None = None


async def _font_bytes() -> bytes:
    global _FONT_BYTES
    if _FONT_BYTES:
        return _FONT_BYTES
    for path in _SYS_FONTS:
        if os.path.exists(path):
            with open(path, "rb") as fh:
                _FONT_BYTES = fh.read()
            return _FONT_BYTES
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(_FONT_URL) as resp:
            resp.raise_for_status()
            _FONT_BYTES = await resp.read()
    return _FONT_BYTES


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(io.BytesIO(_FONT_BYTES), size)


def _wrap(draw, text: str, font, max_width: int) -> list:
    """Перенос по словам под ширину max_width."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit_font(draw, text: str, max_width: int, start: int, min_size: int = 14):
    """Подбирает размер шрифта так, чтобы строка/слово влезли по ширине."""
    size = start
    while size > min_size:
        font = _font(size)
        longest = max(text.split() or [text], key=lambda w: draw.textlength(w, font=font))
        if draw.textlength(longest, font=font) <= max_width:
            return font
        size -= 2
    return _font(min_size)


def _draw_block(draw, lines, font, img_w, y, top: bool):
    """Рисует блок строк (Impact-стиль: белый текст, чёрная обводка)."""
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 4
    if not top:
        y -= line_h * len(lines)
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img_w - w) / 2
        draw.text(
            (x, y), line, font=font, fill="white",
            stroke_width=max(2, font.size // 12), stroke_fill="black",
        )
        y += line_h


def _make_meme(data: bytes, top_text: str, bottom_text: str) -> io.BytesIO:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.width > 1000:
        ratio = 1000 / img.width
        img = img.resize((1000, round(img.height * ratio)), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    margin = int(img.width * 0.04)
    max_w = img.width - margin * 2
    base = max(22, img.width // 9)

    if top_text:
        font = _fit_font(draw, top_text.upper(), max_w, base)
        lines = _wrap(draw, top_text.upper(), font, max_w)
        _draw_block(draw, lines, font, img.width, margin, top=True)
    if bottom_text:
        font = _fit_font(draw, bottom_text.upper(), max_w, base)
        lines = _wrap(draw, bottom_text.upper(), font, max_w)
        _draw_block(draw, lines, font, img.width, img.height - margin, top=False)

    out = io.BytesIO()
    img.save(out, "PNG")
    out.name = "meme.png"
    out.seek(0)
    return out


def _make_demotivator(data: bytes, title: str, subtitle: str) -> io.BytesIO:
    photo = Image.open(io.BytesIO(data)).convert("RGB")
    if photo.width > 800:
        ratio = 800 / photo.width
        photo = photo.resize((800, round(photo.height * ratio)), Image.LANCZOS)
    photo = ImageOps.expand(photo, border=2, fill="white")

    pad_x = int(photo.width * 0.12)
    pad_top = int(photo.height * 0.12)
    canvas_w = photo.width + pad_x * 2

    probe = Image.new("RGB", (10, 10))
    pdraw = ImageDraw.Draw(probe)
    text_w = canvas_w - pad_x
    title_font = _fit_font(pdraw, title or "DEMOTIVATOR", text_w, max(28, canvas_w // 16))
    title_lines = _wrap(pdraw, title, title_font, text_w) if title else []
    sub_font = _font(max(18, canvas_w // 30))
    sub_lines = _wrap(pdraw, subtitle, sub_font, text_w) if subtitle else []

    def _block_h(lines, font):
        if not lines:
            return 0
        a, d = font.getmetrics()
        return (a + d + 6) * len(lines)

    title_h = _block_h(title_lines, title_font)
    sub_h = _block_h(sub_lines, sub_font)
    gap = int(photo.height * 0.04)
    canvas_h = pad_top + photo.height + gap + title_h + sub_h + int(canvas_w * 0.05)

    canvas = Image.new("RGB", (canvas_w, canvas_h), "black")
    canvas.paste(photo, (pad_x, pad_top))
    draw = ImageDraw.Draw(canvas)

    y = pad_top + photo.height + gap
    for line in title_lines:
        w = draw.textlength(line, font=title_font)
        draw.text(((canvas_w - w) / 2, y), line, font=title_font, fill="white")
        a, d = title_font.getmetrics()
        y += a + d + 6
    for line in sub_lines:
        w = draw.textlength(line, font=sub_font)
        draw.text(((canvas_w - w) / 2, y), line, font=sub_font, fill="#cccccc")
        a, d = sub_font.getmetrics()
        y += a + d + 6

    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92)
    out.name = "demotivator.jpg"
    out.seek(0)
    return out


@loader.tds
class DragoMemeMod(loader.Module):
    """🖼 Мем-текст и демотиваторы из картинок по реплаю."""

    strings = {
        "name": "DragoMeme",
        "no_image": (
            "{emoji} <b>Ответь на картинку.</b>\n"
            "<code>{p}meme верх|низ</code> — классический мем\n"
            "<code>{p}dem Заголовок;подпись</code> — демотиватор"
        ),
        "no_text": "{emoji} <b>Дай текст.</b> <code>{p}{cmd} {hint}</code>",
        "making": "{emoji} <b>Рисую…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🖼 Мем-текст и демотиваторы из картинок по реплаю.",
        "memecmd_doc": "верх|низ реплай — классический мем",
        "demcmd_doc": "Заголовок;подпись реплай — демотиватор",
        "no_image": (
            "{emoji} <b>Ответь на картинку.</b>\n"
            "<code>{p}meme верх|низ</code> — классический мем\n"
            "<code>{p}dem Заголовок;подпись</code> — демотиватор"
        ),
        "no_text": "{emoji} <b>Дай текст.</b> <code>{p}{cmd} {hint}</code>",
        "making": "{emoji} <b>Рисую…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "emoji_meme",
                "<emoji document_id=5258502965014076491>🕹</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    @staticmethod
    def _has_image(msg) -> bool:
        if getattr(msg, "photo", None) or getattr(msg, "sticker", None):
            return True
        doc = getattr(msg, "document", None)
        return bool(doc and getattr(doc, "mime_type", "").startswith("image/"))

    async def _prepare(self, message, cmd: str, hint: str):
        emoji = self.config["emoji_meme"]
        reply = await message.get_reply_message()
        if not reply or not self._has_image(reply):
            await utils.answer(
                message, self.strings("no_image").format(emoji=emoji, p=self.get_prefix())
            )
            return None, None, None
        text = (utils.get_args_raw(message) or "").strip()
        if not text:
            await utils.answer(
                message,
                self.strings("no_text").format(
                    emoji=emoji, p=self.get_prefix(), cmd=cmd, hint=hint
                ),
            )
            return None, None, None
        status = await utils.answer(message, self.strings("making").format(emoji=emoji))
        await _font_bytes()
        data = await reply.download_media(bytes)
        return status, reply, data

    @loader.command(ru_doc="верх|низ реплай — классический мем", alias="meme")
    async def memecmd(self, message):
        """top|bottom reply — classic meme"""
        status, reply, data = await self._prepare(message, "meme", "верх|низ")
        if status is None:
            return
        raw = (utils.get_args_raw(message) or "").strip()
        if "|" in raw:
            top, bottom = (p.strip() for p in raw.split("|", 1))
        else:
            top, bottom = raw, ""
        try:
            img = _make_meme(data, top, bottom)
            await self._client.send_file(
                utils.get_chat_id(message), img, reply_to=reply.id, force_document=False,
            )
            await status.delete()
        except Exception as exc:  # noqa: BLE001
            logger.exception("meme failed")
            await utils.answer(status, self.strings("fail").format(utils.escape_html(str(exc))))

    @loader.command(ru_doc="Заголовок;подпись реплай — демотиватор", alias="dem")
    async def demcmd(self, message):
        """Title;subtitle reply — demotivator"""
        status, reply, data = await self._prepare(message, "dem", "Заголовок;подпись")
        if status is None:
            return
        raw = (utils.get_args_raw(message) or "").strip()
        if ";" in raw:
            title, subtitle = (p.strip() for p in raw.split(";", 1))
        else:
            title, subtitle = raw, ""
        try:
            img = _make_demotivator(data, title, subtitle)
            await self._client.send_file(
                utils.get_chat_id(message), img, reply_to=reply.id, force_document=False,
            )
            await status.delete()
        except Exception as exc:  # noqa: BLE001
            logger.exception("demotivator failed")
            await utils.answer(status, self.strings("fail").format(utils.escape_html(str(exc))))
