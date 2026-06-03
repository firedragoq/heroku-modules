__version__ = (1, 0, 1)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: telethon
# changelog: премиум-эмодзи 🔔 по умолчанию

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoTagAll — тегнуть всех участников чата порциями.          ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging

import telethon
from telethon.tl.types import Channel, Chat

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class DragoTagAllMod(loader.Module):
    """📢 Тегнуть всех участников чата порциями (анти-флуд)."""

    strings = {
        "name": "DragoTagAll",
        "not_group": "🚫 <b>Команду нужно выполнять в группе.</b>",
        "running": "📢 <b>Тегаю участников…</b> (по {n} за сообщение)",
        "done": "✅ <b>Готово.</b> Упомянул <b>{n}</b> участников.",
        "stopped": "🛑 <b>Тегание остановлено.</b>",
        "nothing": "🤷 <b>Сейчас нет активного тегания.</b>",
        "no_members": "🤷 <b>Не удалось получить участников.</b>",
        "chunk_header": "{emoji} {text}\n",
    }

    strings_ru = {
        "_cls_doc": "📢 Тегнуть всех участников чата порциями (анти-флуд).",
        "tagallcmd_doc": "[текст] — тегнуть всех участников",
        "tagstopcmd_doc": "остановить тегание",
        "not_group": "🚫 <b>Команду нужно выполнять в группе.</b>",
        "running": "📢 <b>Тегаю участников…</b> (по {n} за сообщение)",
        "done": "✅ <b>Готово.</b> Упомянул <b>{n}</b> участников.",
        "stopped": "🛑 <b>Тегание остановлено.</b>",
        "nothing": "🤷 <b>Сейчас нет активного тегания.</b>",
        "no_members": "🤷 <b>Не удалось получить участников.</b>",
        "chunk_header": "{emoji} {text}\n",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "per_message",
                5,
                "Сколько участников упоминать в одном сообщении (1–10).",
                validator=loader.validators.Integer(minimum=1, maximum=10),
            ),
            loader.ConfigValue(
                "delay",
                3,
                "Пауза между сообщениями, сек (анти-флуд, 1–30).",
                validator=loader.validators.Integer(minimum=1, maximum=30),
            ),
            loader.ConfigValue(
                "skip_bots",
                True,
                "Пропускать ботов.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "skip_deleted",
                True,
                "Пропускать удалённые аккаунты.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "default_text",
                "Внимание!",
                "Текст по умолчанию, если не указан в команде.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_tag",
                "<emoji document_id=5258261274319432461>🔔</emoji>",
                "Эмодзи перед текстом. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )
        self._running = set()

    @staticmethod
    def _mention(user) -> str:
        name = (getattr(user, "first_name", None) or "user").strip() or "user"
        return f'<a href="tg://user?id={user.id}">{utils.escape_html(name)}</a>'

    @loader.command(ru_doc="[текст] — тегнуть всех участников", alias="all")
    async def tagallcmd(self, message: telethon.types.Message):
        """[text] — mention all chat members in chunks"""
        chat = await message.get_chat()
        if not isinstance(chat, (Channel, Chat)) or getattr(chat, "broadcast", False):
            return await utils.answer(message, self.strings("not_group"))

        text = utils.get_args_raw(message).strip() or self.config["default_text"]
        emoji = self.config["emoji_tag"]
        chat_id = utils.get_chat_id(message)

        members = []
        try:
            async for u in self._client.iter_participants(chat_id):
                if self.config["skip_bots"] and getattr(u, "bot", False):
                    continue
                if self.config["skip_deleted"] and getattr(u, "deleted", False):
                    continue
                members.append(u)
        except Exception as exc:  # noqa: BLE001
            logger.exception("iter_participants failed: %s", exc)
            return await utils.answer(message, self.strings("no_members"))

        if not members:
            return await utils.answer(message, self.strings("no_members"))

        per = int(self.config["per_message"])
        delay = int(self.config["delay"])
        await utils.answer(message, self.strings("running").format(n=per))
        self._running.add(chat_id)

        count = 0
        try:
            for i in range(0, len(members), per):
                if chat_id not in self._running:
                    break
                chunk = members[i:i + per]
                mentions = " ".join(self._mention(u) for u in chunk)
                body = self.strings("chunk_header").format(
                    emoji=emoji, text=utils.escape_html(text)
                ) + mentions
                try:
                    await self._client.send_message(chat_id, body, parse_mode="html")
                    count += len(chunk)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("tag chunk failed: %s", exc)
                await asyncio.sleep(delay)
        finally:
            self._running.discard(chat_id)

        await self._client.send_message(
            chat_id, self.strings("done").format(n=count), parse_mode="html"
        )

    @loader.command(ru_doc="остановить тегание", alias="stopall")
    async def tagstopcmd(self, message: telethon.types.Message):
        """Stop an ongoing tag-all"""
        chat_id = utils.get_chat_id(message)
        if chat_id in self._running:
            self._running.discard(chat_id)
            await utils.answer(message, self.strings("stopped"))
        else:
            await utils.answer(message, self.strings("nothing"))
