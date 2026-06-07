__version__ = (1, 0, 1)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: aiohttp
# changelog: фикс — heroku.utils не имеет get_display_name, имя автора собираем сами

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoQuote — красивые цитаты-стикеры из сообщений (Quotly).  ║
# ╚══════════════════════════════════════════════════════════════╝

import base64
import io
import json
import logging

import aiohttp
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    InputStickerSetEmpty,
)

from .. import loader, utils

logger = logging.getLogger(__name__)

# Телетоновские классы сущностей → имена типов Quotly (Bot API style).
_ENT_MAP = {
    "MessageEntityBold": "bold",
    "MessageEntityItalic": "italic",
    "MessageEntityUnderline": "underline",
    "MessageEntityStrike": "strikethrough",
    "MessageEntityCode": "code",
    "MessageEntityPre": "pre",
    "MessageEntitySpoiler": "spoiler",
    "MessageEntityBlockquote": "blockquote",
    "MessageEntityUrl": "url",
    "MessageEntityTextUrl": "text_link",
    "MessageEntityMention": "mention",
    "MessageEntityMentionName": "text_mention",
    "MessageEntityCustomEmoji": "custom_emoji",
}


def _display_name(entity) -> str:
    """Имя автора (heroku.utils не имеет get_display_name из telethon)."""
    if entity is None:
        return "Deleted Account"
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if not name:
        name = (
            getattr(entity, "title", "")
            or getattr(entity, "username", "")
            or "Deleted Account"
        )
    return name


def _entities(msg) -> list:
    """Конвертирует сущности телетон-сообщения в формат, понятный Quotly."""
    out = []
    for e in getattr(msg, "entities", None) or []:
        et = type(e).__name__
        kind = _ENT_MAP.get(et)
        if not kind:
            continue
        d = {"type": kind, "offset": e.offset, "length": e.length}
        if kind == "text_link":
            d["url"] = getattr(e, "url", "")
        elif kind == "pre":
            d["language"] = getattr(e, "language", "") or ""
        elif kind == "text_mention":
            d["user"] = {"id": getattr(e, "user_id", 0)}
        elif kind == "custom_emoji":
            d["custom_emoji_id"] = str(getattr(e, "document_id", ""))
        out.append(d)
    return out


@loader.tds
class DragoQuoteMod(loader.Module):
    """🗯 Красивые цитаты-стикеры из сообщений (Quotly, без ключа)."""

    strings = {
        "name": "DragoQuote",
        "no_reply": (
            "{emoji} <b>Ответь на сообщение</b> командой <code>{p}q</code>.\n"
            "<code>{p}q 3</code> — собрать цитату из 3 сообщений подряд."
        ),
        "empty": "{emoji} <b>Нечего цитировать</b> — в сообщении нет текста.",
        "loading": "{emoji} <b>Рисую цитату…</b>",
        "fail": "🚫 <b>Не удалось сделать цитату:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🗯 Красивые цитаты-стикеры из сообщений (Quotly, без ключа).",
        "quotecmd_doc": "реплай (+N сообщений) — сделать цитату-стикер",
        "no_reply": (
            "{emoji} <b>Ответь на сообщение</b> командой <code>{p}q</code>.\n"
            "<code>{p}q 3</code> — собрать цитату из 3 сообщений подряд."
        ),
        "empty": "{emoji} <b>Нечего цитировать</b> — в сообщении нет текста.",
        "loading": "{emoji} <b>Рисую цитату…</b>",
        "fail": "🚫 <b>Не удалось сделать цитату:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "bg_color",
                "#1b1429",
                "Цвет фона цитаты (hex, rgba или 'random').",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "as_sticker",
                True,
                "Отправлять как стикер (webp). False — как картинку (png).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "avatars",
                True,
                "Показывать аватарки авторов (для юзеров с @username).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "show_reply",
                True,
                "Показывать баббл сообщения, на которое отвечали.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "count_max",
                10,
                "Максимум сообщений в одной цитате.",
                validator=loader.validators.Integer(minimum=1, maximum=30),
            ),
            loader.ConfigValue(
                "api_url",
                "https://bot.lyo.su/quote/generate",
                "Endpoint Quotly. Менять только если основной лежит.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_quote",
                "🗯",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _build_message(self, m) -> dict:
        """Собирает один объект сообщения для Quotly."""
        sender = await m.get_sender()
        name = _display_name(sender)
        frm = {"id": getattr(sender, "id", 0) or 0, "name": name}
        if getattr(sender, "first_name", None):
            frm["first_name"] = sender.first_name
        if getattr(sender, "last_name", None):
            frm["last_name"] = sender.last_name
        username = getattr(sender, "username", None)
        if username:
            frm["username"] = username
            if self.config["avatars"]:
                frm["photo"] = {"url": f"https://t.me/i/userpic/320/{username}.jpg"}

        obj = {
            "from": frm,
            "text": m.raw_text or "",
            "avatar": True,
            "entities": _entities(m),
        }

        # баббл сообщения, на которое отвечали
        if self.config["show_reply"] and getattr(m, "reply_to", None):
            try:
                r = await m.get_reply_message()
                if r:
                    rs = await r.get_sender()
                    obj["replyMessage"] = {
                        "name": _display_name(rs),
                        "text": (r.raw_text or "")[:120],
                        "chatId": getattr(rs, "id", 0) or 0,
                        "entities": [],
                    }
            except Exception:  # noqa: BLE001
                pass
        return obj

    async def _generate(self, messages: list, fmt: str) -> bytes:
        payload = {
            "type": "quote",
            "format": fmt,
            "backgroundColor": self.config["bg_color"],
            "width": 512,
            "height": 768,
            "scale": 2,
            "messages": messages,
        }
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(self.config["api_url"], json=payload) as r:
                body = await r.text()
                if r.status >= 400:
                    raise RuntimeError(f"HTTP {r.status}: {body[:160]}")
                data = json.loads(body)
        img = (data.get("result") or {}).get("image") or data.get("image")
        if not img:
            raise RuntimeError("API не вернул картинку")
        return base64.b64decode(img)

    @loader.command(ru_doc="реплай (+N сообщений) — сделать цитату-стикер", alias="q")
    async def quotecmd(self, message):
        """reply (+N messages) — make a quote sticker"""
        emoji = self.config["emoji_quote"]
        reply = await message.get_reply_message()
        if not reply:
            return await utils.answer(
                message,
                self.strings("no_reply").format(emoji=emoji, p=self.get_prefix()),
            )

        count = 1
        args = utils.get_args_raw(message)
        if args:
            try:
                count = max(1, min(int(self.config["count_max"]), int(args)))
            except ValueError:
                count = 1

        peer = await message.get_input_chat()
        ids = list(range(reply.id, reply.id + count))
        fetched = await self.client.get_messages(peer, ids=ids)
        msgs = [m for m in fetched if m and (m.raw_text or getattr(m, "media", None))]
        if not msgs:
            return await utils.answer(message, self.strings("empty").format(emoji=emoji))

        status = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            built = [await self._build_message(m) for m in msgs]
            fmt = "webp" if self.config["as_sticker"] else "png"
            data = await self._generate(built, fmt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("DragoQuote failed")
            return await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        file = io.BytesIO(data)
        file.name = f"DragoQuote.{fmt}"
        file.seek(0)

        if self.config["as_sticker"]:
            attributes = [
                DocumentAttributeFilename("DragoQuote.webp"),
                DocumentAttributeSticker(alt=emoji, stickerset=InputStickerSetEmpty()),
            ]
            await self.client.send_file(
                peer,
                file,
                reply_to=reply.id,
                attributes=attributes,
                force_document=False,
                mime_type="image/webp",
            )
        else:
            await self.client.send_file(
                peer, file, reply_to=reply.id, force_document=False
            )

        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass
