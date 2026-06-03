__version__ = (1, 1, 1)

# meta developer: @dragomodules
# scope: heroku_only
# requires: qrcode pillow aiohttp
# changelog: use_inline маршрутизирует и .qrread через инлайн-бота

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoQR — генерация и чтение QR-кодов.                        ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import re
from urllib.parse import quote

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

CREATE_API = "https://api.qrserver.com/v1/create-qr-code/?size=500x500&margin=10&data={data}"


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )

try:
    import qrcode

    _QR = True
except ImportError:  # noqa: BLE001
    _QR = False

READ_API = "https://api.qrserver.com/v1/read-qr-code/"


@loader.tds
class DragoQRMod(loader.Module):
    """🔳 Генерация и чтение QR-кодов."""

    strings = {
        "name": "DragoQR",
        "no_text": "🚫 <b>Нет текста.</b> Пример: <code>{p}qr https://t.me/dragomodules</code>",
        "no_lib": "🚫 <b>Библиотека qrcode не установлена.</b>",
        "gen": "🔳 <b>Генерирую QR…</b>",
        "no_photo": "🚫 <b>Ответь на изображение с QR-кодом.</b>",
        "reading": "🔍 <b>Читаю QR…</b>",
        "read_fail": "🚫 <b>QR-код не распознан.</b>",
        "caption": "{emoji} <b>QR-код</b>",
        "read_result": "{emoji} <b>Содержимое QR:</b>\n<code>{data}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🔳 Генерация и чтение QR-кодов.",
        "no_text": "🚫 <b>Нет текста.</b> Пример: <code>{p}qr https://t.me/dragomodules</code>",
        "no_lib": "🚫 <b>Библиотека qrcode не установлена.</b>",
        "gen": "🔳 <b>Генерирую QR…</b>",
        "no_photo": "🚫 <b>Ответь на изображение с QR-кодом.</b>",
        "reading": "🔍 <b>Читаю QR…</b>",
        "read_fail": "🚫 <b>QR-код не распознан.</b>",
        "caption": "{emoji} <b>QR-код</b>",
        "read_result": "{emoji} <b>Содержимое QR:</b>\n<code>{data}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "emoji_qr",
                "🔳",
                "Эмодзи QR. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять QR через инлайн-бота (одним сообщением от бота).",
                validator=loader.validators.Boolean(),
            ),
        )

    @property
    def _inline_on(self) -> bool:
        return bool(self.config["use_inline"]) and getattr(self, "inline", None) is not None

    async def _reply(self, message, text: str):
        if self._inline_on:
            try:
                return await self.inline.form(message=message, text=_to_bot_emoji(text))
            except Exception as exc:  # noqa: BLE001
                logger.warning("inline reply failed, fallback: %s", exc)
        return await utils.answer(message, text)

    async def _status(self, message, text: str):
        if self._inline_on:
            return message
        return await utils.answer(message, text)

    @loader.command(ru_doc="<текст> — сделать QR-код", alias="qrgen")
    async def qrcmd(self, message):
        """<text> — generate a QR code"""
        if not _QR:
            return await utils.answer(message, self.strings("no_lib"))
        text = utils.get_args_raw(message).strip()
        reply = await message.get_reply_message()
        if not text and reply and reply.raw_text:
            text = reply.raw_text
        if not text:
            return await self._reply(
                message, self.strings("no_text").format(p=self.get_prefix())
            )

        # инлайн-режим: QR одним сообщением от бота (картинка по URL qrserver)
        if self.config["use_inline"] and getattr(self, "inline", None):
            try:
                caption = _to_bot_emoji(
                    self.strings("caption").format(emoji=self.config["emoji_qr"])
                )
                return await self.inline.form(
                    message=message,
                    text=caption,
                    photo=CREATE_API.format(data=quote(text, safe="")),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("inline qr failed, fallback: %s", exc)

        msg = await utils.answer(message, self.strings("gen"))
        try:
            qr = qrcode.QRCode(border=2, box_size=10)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            buf.name = "qr.png"
            img.save(buf, "PNG")
            buf.seek(0)
            await utils.answer(
                message=message,
                response=self.strings("caption").format(emoji=self.config["emoji_qr"]),
                file=buf,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("qr gen failed: %s", exc)
            await utils.answer(msg, self.strings("fail").format(exc))

    @loader.command(ru_doc="прочитать QR с картинки (реплай)", alias="qrread")
    async def qrdcmd(self, message):
        """Read QR from a replied image"""
        reply = await message.get_reply_message()
        if not reply or not reply.photo and not reply.document:
            return await self._reply(message, self.strings("no_photo"))
        await self._status(message, self.strings("reading"))
        try:
            img_bytes = await reply.download_media(bytes)
            form = aiohttp.FormData()
            form.add_field("file", img_bytes, filename="qr.png", content_type="image/png")
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(READ_API, data=form) as resp:
                    data = await resp.json(content_type=None)
            symbol = data[0]["symbol"][0]
            content = symbol.get("data")
            if not content:
                return await self._reply(message, self.strings("read_fail"))
            await self._reply(
                message,
                self.strings("read_result").format(
                    emoji=self.config["emoji_qr"], data=utils.escape_html(content)
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("qr read failed: %s", exc)
            await self._reply(message, self.strings("fail").format(exc))
