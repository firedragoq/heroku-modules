__version__ = (1, 1, 0)

# meta developer: @firedragoq
# scope: heroku_only
# requires: telethon

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoModUpdates — установка модулей из канала в один тап.     ║
# ║  Работает в паре с ботом-витриной модулей.                     ║
# ╚══════════════════════════════════════════════════════════════╝

import logging

from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Должно совпадать с INSTALL_MARKER в боте (bot/handlers/user.py)
INSTALL_MARKER = "#HerokuModInstall"


@loader.tds
class DragoModUpdatesMod(loader.Module):
    """🆕 Установка модулей из канала-витрины в один тап."""

    strings = {
        "name": "DragoModUpdates",
        "no_bot": "🚫 <b>Укажи юзернейм бота в конфиге</b> (<code>{}cfg DragoModUpdates</code>).",
        "connecting": "🔗 <b>Подключаюсь к боту…</b>",
        "connected": (
            "✅ <b>Готово!</b> Аккаунт подключён к боту "
            "<code>@{}</code>.\n\nТеперь жми «Установить в Heroku» под "
            "модулями в канале."
        ),
        "disconnected": "👋 <b>Отключено.</b> Открой бота и нажми /start ещё раз для повторного подключения.",
        "installing": "📥 <b>Устанавливаю модуль…</b>\n<code>{}</code>",
        "install_ok": "✅ <b>Модуль установлен:</b> <code>{}</code>",
        "install_fail": "🚫 <b>Не удалось установить модуль.</b>\n<code>{}</code>",
        "status": (
            "📦 <b>DragoModUpdates</b>\n\n"
            "🤖 Бот: <code>@{bot}</code>\n"
            "🔌 Подключение: <b>{state}</b>\n"
            "📥 Установлено через бота: <b>{count}</b>"
        ),
    }

    strings_ru = {
        "no_bot": "🚫 <b>Укажи юзернейм бота в конфиге</b> (<code>{}cfg DragoModUpdates</code>).",
        "connecting": "🔗 <b>Подключаюсь к боту…</b>",
        "connected": (
            "✅ <b>Готово!</b> Аккаунт подключён к боту "
            "<code>@{}</code>.\n\nТеперь жми «Установить в Heroku» под "
            "модулями в канале."
        ),
        "disconnected": "👋 <b>Отключено.</b> Открой бота и нажми /start ещё раз для повторного подключения.",
        "installing": "📥 <b>Устанавливаю модуль…</b>\n<code>{}</code>",
        "install_ok": "✅ <b>Модуль установлен:</b> <code>{}</code>",
        "install_fail": "🚫 <b>Не удалось установить модуль.</b>\n<code>{}</code>",
        "status": (
            "📦 <b>DragoModUpdates</b>\n\n"
            "🤖 Бот: <code>@{bot}</code>\n"
            "🔌 Подключение: <b>{state}</b>\n"
            "📥 Установлено через бота: <b>{count}</b>"
        ),
        "_cls_doc": "🆕 Установка модулей из канала-витрины в один тап.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "bot_username",
                "dragomodules_bot",
                "Юзернейм бота-витрины модулей (без @).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "auto_install",
                True,
                "Автоматически ставить модуль при нажатии кнопки в канале.",
                validator=loader.validators.Boolean(),
            ),
        )
        self._bot_id = None

    async def client_ready(self, client, db):
        self._client = client
        self._db = db
        await self._resolve_bot()

    def _bot_uname(self) -> str:
        return str(self.config["bot_username"]).lstrip("@")

    async def _resolve_bot(self):
        uname = self._bot_uname()
        if not uname:
            return
        try:
            entity = await self._client.get_entity(uname)
            self._bot_id = entity.id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось получить бота @%s: %s", uname, exc)

    @loader.command(ru_doc="Подключить аккаунт к боту-витрине")
    async def modconnectcmd(self, message: Message):
        """Connect your account to the modules bot"""
        uname = self._bot_uname()
        if not uname:
            await utils.answer(message, self.strings("no_bot").format(self.get_prefix()))
            return
        await utils.answer(message, self.strings("connecting"))
        await self._resolve_bot()
        # стартуем бота с пейлоадом connect — он запомнит наш user_id
        await self._client.send_message(uname, "/start connect")
        await utils.answer(message, self.strings("connected").format(uname))

    @loader.command(ru_doc="Отключить аккаунт от бота-витрины")
    async def modunconnectcmd(self, message: Message):
        """Disconnect from the modules bot"""
        uname = self._bot_uname()
        if uname:
            try:
                await self._client.send_message(uname, "/unauth")
            except Exception:  # noqa: BLE001
                pass
        await utils.answer(message, self.strings("disconnected"))

    @loader.command(ru_doc="Статус подключения к боту-витрине")
    async def modstatuscmd(self, message: Message):
        """Show connection status"""
        count = self._db.get(self.strings["name"], "installed", 0)
        await utils.answer(
            message,
            self.strings("status").format(
                bot=self._bot_uname() or "—",
                state="активно ✅" if self._bot_id else "не настроено ⚠️",
                count=count,
            ),
        )

    async def _install(self, url: str, reply_chat):
        """Скачивает и устанавливает модуль по ссылке."""
        notice = await self._client.send_message(
            reply_chat, self.strings("installing").format(url)
        )
        ok = False
        try:
            loader_mod = self.lookup("loader")
            if loader_mod and hasattr(loader_mod, "download_and_install"):
                await loader_mod.download_and_install(url, None)
                ok = True
            else:
                # запасной путь — выполнить команду .dlmod в Избранном
                await self._client.send_message(
                    "me", f"{self.get_prefix()}dlmod {url}"
                )
                ok = True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка установки %s: %s", url, exc)
            await notice.edit(self.strings("install_fail").format(exc))
            return

        if ok:
            count = self._db.get(self.strings["name"], "installed", 0) + 1
            self._db.set(self.strings["name"], "installed", count)
            await notice.edit(self.strings("install_ok").format(url))

    @loader.watcher(only_messages=True)
    async def watcher(self, message: Message):
        """Ловит служебные сообщения от бота и ставит модули."""
        if not self.config["auto_install"]:
            return
        if getattr(message, "out", False):
            return
        if self._bot_id is None:
            await self._resolve_bot()
        sender_id = getattr(message, "sender_id", None)
        if self._bot_id and sender_id != self._bot_id:
            return
        text = message.raw_text or ""
        if INSTALL_MARKER not in text:
            return
        # формат: "#HerokuModInstall\n<url>"
        url = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("http"):
                url = line
                break
        if not url:
            return
        await self._install(url, message.chat_id)
