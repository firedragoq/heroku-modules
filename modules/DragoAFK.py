__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: telethon

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoAFK — авто-ответ «отошёл» на ЛС и упоминания.            ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import time

from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)


def _ago(seconds: int) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if not parts:
        parts.append(f"{s}с")
    return " ".join(parts)


@loader.tds
class DragoAFKMod(loader.Module):
    """💤 Авто-ответ «отошёл» на ЛС и упоминания."""

    strings = {
        "name": "DragoAFK",
        "afk_on": "{emoji} <b>Режим AFK включён.</b>\n📝 Причина: <i>{reason}</i>",
        "afk_on_noreason": "{emoji} <b>Режим AFK включён.</b>",
        "afk_off": "✅ <b>Я вернулся!</b> Отсутствовал: <b>{dur}</b>",
        "reply": (
            "{emoji} <b>Сейчас я не в сети (AFK)</b>\n"
            "{reason}⏱ Отошёл: <b>{dur}</b> назад"
        ),
    }

    strings_ru = {
        "_cls_doc": "💤 Авто-ответ «отошёл» на ЛС и упоминания.",
        "afk_on": "{emoji} <b>Режим AFK включён.</b>\n📝 Причина: <i>{reason}</i>",
        "afk_on_noreason": "{emoji} <b>Режим AFK включён.</b>",
        "afk_off": "✅ <b>Я вернулся!</b> Отсутствовал: <b>{dur}</b>",
        "reply": (
            "{emoji} <b>Сейчас я не в сети (AFK)</b>\n"
            "{reason}⏱ Отошёл: <b>{dur}</b> назад"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "emoji_afk",
                "💤",
                "Эмодзи AFK. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "cooldown",
                60,
                "Не отвечать в один чат чаще, чем раз в N секунд.",
                validator=loader.validators.Integer(minimum=5, maximum=3600),
            ),
            loader.ConfigValue(
                "reply_private",
                True,
                "Отвечать на сообщения в личке.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "reply_mention",
                True,
                "Отвечать на упоминания/реплаи в группах.",
                validator=loader.validators.Boolean(),
            ),
        )
        self._last_reply: dict[int, float] = {}

    async def client_ready(self, client, db):
        self._db = db

    @loader.command(ru_doc="[причина] — включить AFK", alias="afk")
    async def afkoncmd(self, message: Message):
        """[reason] — enable AFK"""
        reason = utils.get_args_raw(message).strip()
        self.set("afk", {"since": time.time(), "reason": reason})
        self._last_reply.clear()
        emoji = self.config["emoji_afk"]
        if reason:
            await utils.answer(
                message, self.strings("afk_on").format(emoji=emoji, reason=utils.escape_html(reason))
            )
        else:
            await utils.answer(message, self.strings("afk_on_noreason").format(emoji=emoji))

    @loader.command(ru_doc="выключить AFK", alias="unafk")
    async def afkoffcmd(self, message: Message):
        """Disable AFK"""
        afk = self.get("afk")
        self.set("afk", None)
        dur = _ago(time.time() - afk["since"]) if afk else "0с"
        await utils.answer(message, self.strings("afk_off").format(dur=dur))

    @loader.watcher()
    async def watcher(self, message: Message):
        afk = self.get("afk")
        if not afk:
            return
        text = message.raw_text or ""

        # моя активность — выходим из AFK (но не на саму команду .afk)
        if getattr(message, "out", False):
            prefix = self.get_prefix()
            if text.startswith(f"{prefix}afk") or text.startswith(f"{prefix}unafk"):
                return
            if time.time() - afk["since"] < 2:
                return
            self.set("afk", None)
            try:
                await self._client.send_message(
                    message.chat_id,
                    self.strings("afk_off").format(dur=_ago(time.time() - afk["since"])),
                )
            except Exception:  # noqa: BLE001
                pass
            return

        # входящее: отвечаем на ЛС или упоминание
        is_private = message.is_private
        is_mention = bool(getattr(message, "mentioned", False))
        if is_private and not self.config["reply_private"]:
            return
        if not is_private and not (is_mention and self.config["reply_mention"]):
            return

        chat_id = message.chat_id
        now = time.time()
        if now - self._last_reply.get(chat_id, 0) < int(self.config["cooldown"]):
            return
        self._last_reply[chat_id] = now

        reason = afk.get("reason", "")
        reason_line = f"📝 <i>{utils.escape_html(reason)}</i>\n" if reason else ""
        try:
            await message.reply(
                self.strings("reply").format(
                    emoji=self.config["emoji_afk"],
                    reason=reason_line,
                    dur=_ago(now - afk["since"]),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("afk reply failed: %s", exc)
