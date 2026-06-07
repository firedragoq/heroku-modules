__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: Pillow
# changelog: первый релиз — фото/реплай → стикер (.stick) и добавление в свой пак (.kang)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoSticker — фото/реплай → стикер и добавление в свой пак. ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import random
import string

from PIL import Image
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    InputStickerSetEmpty,
)

from .. import loader, utils

logger = logging.getLogger(__name__)

STICKERS_BOT = "Stickers"


class _KangError(Exception):
    """Ошибка диалога со @Stickers (показываем ответ бота пользователю)."""


def _to_512(data: bytes, fmt: str) -> io.BytesIO:
    """Масштабирует картинку: длинная сторона = 512 (требование стикеров)."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = img.size
    scale = 512 / max(w, h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, fmt.upper())
    out.name = f"sticker.{fmt}"
    out.seek(0)
    return out


@loader.tds
class DragoStickerMod(loader.Module):
    """🧩 Фото/реплай → стикер и добавление в свой стикерпак."""

    strings = {
        "name": "DragoSticker",
        "no_media": (
            "{emoji} <b>Ответь на фото/картинку/стикер</b> командой "
            "<code>{p}stick</code> (или <code>{p}kang 🔥</code> — в свой пак)."
        ),
        "making": "{emoji} <b>Делаю стикер…</b>",
        "kanging": "{emoji} <b>Добавляю в пак…</b> (общаюсь со @Stickers)",
        "kang_ok": (
            "{emoji} <b>Готово!</b> Стикер в паке <a href=\"{link}\">{title}</a> "
            "(эмодзи {e})."
        ),
        "kang_fail": (
            "🚫 <b>Не удалось добавить в пак.</b>\nОтвет @Stickers:\n<code>{}</code>"
        ),
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🧩 Фото/реплай → стикер и добавление в свой стикерпак.",
        "stickcmd_doc": "реплай — превратить картинку в стикер",
        "kangcmd_doc": "[эмодзи] реплай — добавить стикер в свой пак",
        "no_media": (
            "{emoji} <b>Ответь на фото/картинку/стикер</b> командой "
            "<code>{p}stick</code> (или <code>{p}kang 🔥</code> — в свой пак)."
        ),
        "making": "{emoji} <b>Делаю стикер…</b>",
        "kanging": "{emoji} <b>Добавляю в пак…</b> (общаюсь со @Stickers)",
        "kang_ok": (
            "{emoji} <b>Готово!</b> Стикер в паке <a href=\"{link}\">{title}</a> "
            "(эмодзи {e})."
        ),
        "kang_fail": (
            "🚫 <b>Не удалось добавить в пак.</b>\nОтвет @Stickers:\n<code>{}</code>"
        ),
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "default_emoji",
                "🔥",
                "Эмодзи по умолчанию для стикера в паке.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "pack_title",
                "DragoModules Pack",
                "Название создаваемого стикерпака.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_sticker",
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

    @loader.command(ru_doc="реплай — превратить картинку в стикер", alias="stick")
    async def stickcmd(self, message):
        """reply — turn an image into a sticker"""
        emoji = self.config["emoji_sticker"]
        reply = await message.get_reply_message()
        if not reply or not self._has_image(reply):
            return await utils.answer(
                message, self.strings("no_media").format(emoji=emoji, p=self.get_prefix())
            )
        status = await utils.answer(message, self.strings("making").format(emoji=emoji))
        try:
            data = await reply.download_media(bytes)
            webp = _to_512(data, "webp")
            attributes = [
                DocumentAttributeFilename("DragoSticker.webp"),
                DocumentAttributeSticker(alt="🔥", stickerset=InputStickerSetEmpty()),
            ]
            await self._client.send_file(
                utils.get_chat_id(message),
                webp,
                reply_to=reply.id,
                attributes=attributes,
                force_document=False,
                mime_type="image/webp",
            )
            await status.delete()
        except Exception as exc:  # noqa: BLE001
            logger.exception("stick failed")
            await utils.answer(status, self.strings("fail").format(utils.escape_html(str(exc))))

    @loader.command(ru_doc="[эмодзи] реплай — добавить стикер в свой пак", alias="kang")
    async def kangcmd(self, message):
        """[emoji] reply — add a sticker to your pack"""
        emoji = self.config["emoji_sticker"]
        reply = await message.get_reply_message()
        if not reply or not self._has_image(reply):
            return await utils.answer(
                message, self.strings("no_media").format(emoji=emoji, p=self.get_prefix())
            )
        sticker_emoji = (utils.get_args_raw(message) or "").strip() or self.config["default_emoji"]
        status = await utils.answer(message, self.strings("kanging").format(emoji=emoji))
        try:
            data = await reply.download_media(bytes)
            png = _to_512(data, "png")
            link, title = await self._kang(png, sticker_emoji)
        except _KangError as exc:
            return await utils.answer(
                status, self.strings("kang_fail").format(utils.escape_html(str(exc)))
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("kang failed")
            return await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)))
            )
        await utils.answer(
            status,
            self.strings("kang_ok").format(
                emoji=emoji, link=link, title=utils.escape_html(title), e=sticker_emoji
            ),
        )

    async def _kang(self, png: io.BytesIO, sticker_emoji: str):
        """Добавляет PNG в пак через диалог со @Stickers. Возвращает (ссылка, название)."""
        pack = self.get("pack")
        async with self._client.conversation(STICKERS_BOT) as conv:
            if not pack:
                short = self._new_short()
                title = str(self.config["pack_title"])
                await self._send_wait(conv, "/newpack")
                await self._send_wait(conv, title)
                await self._send_file_wait(conv, png)
                await self._send_wait(conv, sticker_emoji)
                await self._send_wait(conv, "/publish")
                # @Stickers иногда просит иконку — пропускаем
                await self._send_wait(conv, "/skip")
                r = await self._send_wait(conv, short)
                if "http" not in (r or "").lower() and "addstickers" not in (r or "").lower():
                    raise _KangError(r or "нет ответа на короткое имя")
                pack = {"short": short, "title": title}
                self.set("pack", pack)
            else:
                r = await self._send_wait(conv, "/addsticker")
                r = await self._send_wait(conv, pack["short"])
                # пак переполнен — заводим новый
                if "full" in (r or "").lower() or "120" in (r or ""):
                    self.set("pack", None)
                    return await self._kang(png, sticker_emoji)
                await self._send_file_wait(conv, png)
                await self._send_wait(conv, sticker_emoji)
                await self._send_wait(conv, "/done")
        return f"https://t.me/addstickers/{pack['short']}", pack["title"]

    @staticmethod
    def _new_short() -> str:
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"drago_{rand}_pack"

    @staticmethod
    async def _send_wait(conv, text: str) -> str:
        await conv.send_message(text)
        try:
            resp = await conv.get_response(timeout=30)
            return resp.raw_text or ""
        except Exception as exc:  # noqa: BLE001
            raise _KangError(f"нет ответа на «{text}»: {exc}")

    @staticmethod
    async def _send_file_wait(conv, file: io.BytesIO) -> str:
        file.seek(0)
        await conv.send_file(file, force_document=True)
        try:
            resp = await conv.get_response(timeout=30)
            return resp.raw_text or ""
        except Exception as exc:  # noqa: BLE001
            raise _KangError(f"нет ответа на файл: {exc}")
