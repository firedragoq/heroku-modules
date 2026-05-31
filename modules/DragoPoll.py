__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoPoll — быстрые опросы/голосования в чате (нативный poll). ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import random

import telethon
from telethon.tl.types import InputMediaPoll, Poll, PollAnswer

from .. import loader, utils

logger = logging.getLogger(__name__)


def _twe(text: str):
    """Текст для poll: TextWithEntities (новый Telethon) или str (старый)."""
    try:
        from telethon.tl.types import TextWithEntities

        return TextWithEntities(text=text, entities=[])
    except Exception:  # noqa: BLE001
        return text


@loader.tds
class DragoPollMod(loader.Module):
    """🗳 Быстрые опросы и голосования в чате (нативный Telegram poll)."""

    strings = {
        "name": "DragoPoll",
        "usage": (
            "{emoji} <b>DragoPoll</b>\n\n"
            "<code>{p}poll Вопрос | вариант 1 | вариант 2 | …</code>\n\n"
            "Разделитель — <code>|</code> (или новые строки). От 2 до 10 вариантов.\n"
            "Анонимность и мультивыбор настраиваются в <code>{p}cfg DragoPoll</code>."
        ),
        "need_options": (
            "🚫 <b>Нужен вопрос и минимум 2 варианта.</b>\n"
            "Пример: <code>{p}poll Пицца или суши? | Пицца | Суши</code>"
        ),
        "too_many": "🚫 <b>Слишком много вариантов</b> (максимум 10).",
        "fail": "🚫 <b>Не удалось создать опрос:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🗳 Быстрые опросы и голосования в чате (нативный Telegram poll).",
        "pollcmd_doc": "<вопрос> | <вар1> | <вар2> … — создать опрос",
        "usage": (
            "{emoji} <b>DragoPoll</b>\n\n"
            "<code>{p}poll Вопрос | вариант 1 | вариант 2 | …</code>\n\n"
            "Разделитель — <code>|</code> (или новые строки). От 2 до 10 вариантов.\n"
            "Анонимность и мультивыбор настраиваются в <code>{p}cfg DragoPoll</code>."
        ),
        "need_options": (
            "🚫 <b>Нужен вопрос и минимум 2 варианта.</b>\n"
            "Пример: <code>{p}poll Пицца или суши? | Пицца | Суши</code>"
        ),
        "too_many": "🚫 <b>Слишком много вариантов</b> (максимум 10).",
        "fail": "🚫 <b>Не удалось создать опрос:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "anonymous",
                True,
                "Анонимный опрос (не видно, кто как голосовал).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "multiple_choice",
                False,
                "Разрешить выбирать несколько вариантов.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_poll",
                "🗳",
                "Эмодзи опроса. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    @staticmethod
    def _split(raw: str) -> list[str]:
        """Делит ввод на части по | или переводам строк."""
        if "|" in raw:
            parts = raw.split("|")
        else:
            parts = raw.splitlines()
        return [p.strip() for p in parts if p.strip()]

    @loader.command(ru_doc="<вопрос> | <вар1> | <вар2> … — создать опрос")
    async def pollcmd(self, message: telethon.types.Message):
        """<question> | <opt1> | <opt2> … — create a poll"""
        raw = utils.get_args_raw(message).strip()
        if not raw:
            return await utils.answer(
                message,
                self.strings("usage").format(
                    emoji=self.config["emoji_poll"], p=self.get_prefix()
                ),
            )

        parts = self._split(raw)
        if len(parts) < 3:
            return await utils.answer(
                message, self.strings("need_options").format(p=self.get_prefix())
            )

        question, options = parts[0], parts[1:]
        if len(options) > 10:
            return await utils.answer(message, self.strings("too_many"))

        poll = Poll(
            id=random.getrandbits(63),
            question=_twe(question[:255]),
            answers=[
                PollAnswer(text=_twe(opt[:100]), option=bytes([i]))
                for i, opt in enumerate(options)
            ],
            closed=False,
            public_voters=not self.config["anonymous"],
            multiple_choice=bool(self.config["multiple_choice"]),
        )

        try:
            await self._client.send_file(
                utils.get_chat_id(message),
                InputMediaPoll(poll=poll),
                reply_to=getattr(message, "reply_to_msg_id", None),
            )
            if message.out:
                await message.delete()
        except Exception as exc:  # noqa: BLE001
            logger.exception("poll failed: %s", exc)
            await utils.answer(message, self.strings("fail").format(utils.escape_html(str(exc))))
