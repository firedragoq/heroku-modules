__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only

# ╔══════════════════════════════════════════════════════════════╗
# ║  EmojiDump — временный помощник: выводит document_id эмодзи    ║
# ║  из набора кастом-эмодзи по его short_name. Потом удалить.     ║
# ╚══════════════════════════════════════════════════════════════╝

import logging

import telethon
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import InputStickerSetShortName

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class EmojiDumpMod(loader.Module):
    """🧪 Вывести document_id эмодзи из набора (по short_name)."""

    strings = {
        "name": "EmojiDump",
        "no_arg": (
            "🚫 <b>Укажи short_name набора.</b>\n"
            "Пример: <code>{p}emojidump VpnfiredragoqBot</code>\n"
            "(short_name — хвост ссылки t.me/addemoji/<b>…</b>)"
        ),
        "loading": "🧪 <b>Получаю набор…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🧪 Вывести document_id эмодзи из набора (по short_name).",
        "emojidumpcmd_doc": "<short_name> — вывести id эмодзи набора",
    }

    @loader.command(ru_doc="<short_name> — вывести id эмодзи набора")
    async def emojidumpcmd(self, message: telethon.types.Message):
        """<short_name> — dump custom emoji document ids from a set"""
        name = utils.get_args_raw(message).strip().lstrip("@")
        # вытащим из ссылки, если прислали целиком
        if "addemoji/" in name:
            name = name.split("addemoji/")[-1].strip("/")
        if not name:
            return await utils.answer(
                message, self.strings("no_arg").format(p=self.get_prefix())
            )

        await utils.answer(message, self.strings("loading"))
        try:
            res = await self._client(
                GetStickerSetRequest(
                    stickerset=InputStickerSetShortName(short_name=name), hash=0
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("getStickerSet failed: %s", exc)
            return await utils.answer(
                message, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        # сопоставим document_id → эмодзи (emoticon) из packs
        id_to_emoji = {}
        for pack in res.packs:
            for doc_id in pack.documents:
                id_to_emoji.setdefault(doc_id, pack.emoticon)

        lines = [f"<b>Набор:</b> <code>{utils.escape_html(res.set.title)}</code> "
                 f"({len(res.documents)} шт.)\n"]
        for doc in res.documents:
            emo = id_to_emoji.get(doc.id, "❓")
            # строка готова к копированию в формате <tg-emoji>
            lines.append(
                f"{emo} <code>{doc.id}</code> — "
                f"<code>&lt;tg-emoji emoji-id=\"{doc.id}\"&gt;{emo}&lt;/tg-emoji&gt;</code>"
            )

        # шлём по частям, чтобы не упереться в лимит 4096
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                await self._client.send_message(
                    utils.get_chat_id(message), chunk, parse_mode="html"
                )
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await utils.answer(message, chunk)
