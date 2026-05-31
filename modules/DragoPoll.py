__version__ = (1, 1, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# changelog: премиум-эмодзи в вопросе и вариантах опроса (перенос custom_emoji entities)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoPoll — быстрые опросы/голосования в чате (нативный poll). ║
# ║  Поддержка премиум-эмодзи в вопросе и вариантах.                ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import random

import telethon
from telethon.tl.types import (
    InputMediaPoll,
    MessageEntityCustomEmoji,
    Poll,
    PollAnswer,
)

from .. import loader, utils

logger = logging.getLogger(__name__)


def _u16(s: str) -> int:
    """Длина строки в кодовых единицах UTF-16 (как считает Telegram offset/length)."""
    return len(s.encode("utf-16-le")) // 2


def _twe(text: str, entities=None):
    """Текст для poll: TextWithEntities (новый Telethon) или str (старый)."""
    try:
        from telethon.tl.types import TextWithEntities

        return TextWithEntities(text=text, entities=entities or [])
    except Exception:  # noqa: BLE001
        return text


def _make_poll(**kwargs) -> Poll:
    """Создаёт Poll, подстраиваясь под версию Telethon (поле hash то есть, то нет)."""
    try:
        return Poll(**kwargs)
    except TypeError as exc:
        if "hash" in str(exc):
            return Poll(hash=0, **kwargs)
        raise


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
    def _custom_emoji(message) -> list:
        return [
            e for e in (message.entities or [])
            if isinstance(e, MessageEntityCustomEmoji)
        ]

    def _segment(self, piece: str, seg_abs_u16: int, custom: list, limit: int):
        """Из куска текста делает (stripped_text, [entities]) с пересчётом offset'ов.

        seg_abs_u16 — абсолютный UTF-16 offset начала piece в исходном сообщении.
        Берём только те custom_emoji, что целиком попадают в обрезанный кусок.
        """
        lead = len(piece) - len(piece.lstrip())
        stripped = piece.strip()[:limit]
        if not stripped:
            return "", []
        start = seg_abs_u16 + _u16(piece[:lead])
        end = start + _u16(stripped)
        ents = [
            MessageEntityCustomEmoji(
                offset=e.offset - start, length=e.length, document_id=e.document_id
            )
            for e in custom
            if e.offset >= start and e.offset + e.length <= end
        ]
        return stripped, ents

    def _parse_segments(self, message, tail: str, tail_abs_u16: int):
        """Делит tail по | (или строкам) и возвращает [(text, entities), …]."""
        custom = self._custom_emoji(message)
        sep = "|" if "|" in tail else "\n"
        out = []
        idx = 0
        for i, piece in enumerate(tail.split(sep)):
            seg_abs = tail_abs_u16 + _u16(tail[:idx])
            # вопрос (первый сегмент) до 255 символов, варианты — до 100
            text, ents = self._segment(piece, seg_abs, custom, 255 if i == 0 else 100)
            if text:
                out.append((text, ents))
            idx += len(piece) + len(sep)
        return out

    @loader.command(ru_doc="<вопрос> | <вар1> | <вар2> … — создать опрос")
    async def pollcmd(self, message: telethon.types.Message):
        """<question> | <opt1> | <opt2> … — create a poll"""
        raw = (message.raw_text or "")
        # отделяем команду (префикс+cmd) от аргументов по первому пробелу/переводу строки
        head = raw
        ws_pos = next((i for i, c in enumerate(raw) if c.isspace()), -1)
        if ws_pos == -1:
            return await utils.answer(
                message,
                self.strings("usage").format(
                    emoji=self.config["emoji_poll"], p=self.get_prefix()
                ),
            )
        head = raw[:ws_pos + 1]
        tail = raw[ws_pos + 1:]
        if not tail.strip():
            return await utils.answer(
                message,
                self.strings("usage").format(
                    emoji=self.config["emoji_poll"], p=self.get_prefix()
                ),
            )

        segments = self._parse_segments(message, tail, _u16(head))
        if len(segments) < 3:
            return await utils.answer(
                message, self.strings("need_options").format(p=self.get_prefix())
            )

        (q_text, q_ents), options = segments[0], segments[1:]
        if len(options) > 10:
            return await utils.answer(message, self.strings("too_many"))

        poll = _make_poll(
            id=random.getrandbits(63),
            question=_twe(q_text, q_ents),
            answers=[
                PollAnswer(text=_twe(opt, ents), option=bytes([i]))
                for i, (opt, ents) in enumerate(options)
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
