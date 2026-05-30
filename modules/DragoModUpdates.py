__version__ = (1, 2, 2)

# meta developer: @dragomodules
# scope: heroku_only
# requires: telethon aiohttp
# changelog: подписка на канал при установке (meta developer → @dragomodules)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoModUpdates — установка модулей из канала в один тап.     ║
# ║  Работает в паре с ботом-витриной модулей. Умеет обновлять     ║
# ║  сам себя из репозитория.                                      ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import re
import time

import aiohttp
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Должно совпадать с INSTALL_MARKER в боте (bot/handlers/user.py)
INSTALL_MARKER = "#HerokuModInstall"

# Версия запущенного модуля — для сравнения с версией в репозитории
SELF_VERSION = __version__

_VERSION_RE = re.compile(r"__version__\s*=\s*\(([^)]+)\)")


def _parse_version(text: str):
    """Достаёт __version__ из исходника модуля как кортеж чисел."""
    m = _VERSION_RE.search(text)
    if not m:
        return None
    parts = []
    for piece in m.group(1).split(","):
        piece = piece.strip()
        if piece.isdigit():
            parts.append(int(piece))
    return tuple(parts) if parts else None


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
            "📦 <b>DragoModUpdates</b> <code>v{ver}</code>\n\n"
            "🤖 Бот: <code>@{bot}</code>\n"
            "🔌 Подключение: <b>{state}</b>\n"
            "📥 Установлено через бота: <b>{count}</b>\n"
            "🔄 Автообновление: <b>{auto}</b>"
        ),
        "checking_self": "🔄 <b>Проверяю обновления DragoModUpdates…</b>",
        "self_uptodate": "✅ <b>DragoModUpdates</b> уже последней версии (<code>v{}</code>).",
        "self_updating": (
            "🆕 <b>Найдена новая версия DragoModUpdates:</b> "
            "<code>v{old}</code> → <code>v{new}</code>\n♻️ Обновляюсь…"
        ),
        "self_updated": "✅ <b>DragoModUpdates обновлён до</b> <code>v{}</code>!",
        "self_fail": "🚫 <b>Не удалось обновить DragoModUpdates.</b>\n<code>{}</code>",
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
            "📦 <b>DragoModUpdates</b> <code>v{ver}</code>\n\n"
            "🤖 Бот: <code>@{bot}</code>\n"
            "🔌 Подключение: <b>{state}</b>\n"
            "📥 Установлено через бота: <b>{count}</b>\n"
            "🔄 Автообновление: <b>{auto}</b>"
        ),
        "checking_self": "🔄 <b>Проверяю обновления DragoModUpdates…</b>",
        "self_uptodate": "✅ <b>DragoModUpdates</b> уже последней версии (<code>v{}</code>).",
        "self_updating": (
            "🆕 <b>Найдена новая версия DragoModUpdates:</b> "
            "<code>v{old}</code> → <code>v{new}</code>\n♻️ Обновляюсь…"
        ),
        "self_updated": "✅ <b>DragoModUpdates обновлён до</b> <code>v{}</code>!",
        "self_fail": "🚫 <b>Не удалось обновить DragoModUpdates.</b>\n<code>{}</code>",
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
            loader.ConfigValue(
                "auto_update",
                True,
                "Автоматически обновлять сам DragoModUpdates из репозитория.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "self_url",
                "https://raw.githubusercontent.com/firedragoq/"
                "heroku-modules/main/modules/DragoModUpdates.py",
                "Ссылка на исходник DragoModUpdates для самообновления.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "update_interval",
                6,
                "Как часто (в часах) проверять обновление самого себя.",
                validator=loader.validators.Integer(minimum=1),
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
                ver=".".join(map(str, SELF_VERSION)),
                bot=self._bot_uname() or "—",
                state="активно ✅" if self._bot_id else "не настроено ⚠️",
                count=count,
                auto="вкл ✅" if self.config["auto_update"] else "выкл ⛔",
            ),
        )

    @loader.command(ru_doc="Проверить и обновить сам DragoModUpdates")
    async def modupdatecmd(self, message: Message):
        """Check & self-update DragoModUpdates"""
        msg = await utils.answer(message, self.strings("checking_self"))
        await self._check_self_update(reply=msg)

    # ───────────────────── самообновление ─────────────────────
    async def _fetch(self, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text()

    async def _check_self_update(self, reply: Message = None) -> bool:
        """Проверяет версию себя в репозитории и обновляется, если новее."""
        url = self.config["self_url"]
        cur_str = ".".join(map(str, SELF_VERSION))
        try:
            source = await self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Self-update fetch failed: %s", exc)
            if reply:
                await reply.edit(self.strings("self_fail").format(exc))
            return False

        remote = _parse_version(source)
        if not remote or remote <= SELF_VERSION:
            if reply:
                await reply.edit(self.strings("self_uptodate").format(cur_str))
            return False

        # есть более новая версия — обновляемся
        new_str = ".".join(map(str, remote))
        text = self.strings("self_updating").format(old=cur_str, new=new_str)
        notice = reply
        if notice is None:
            notice = await self._client.send_message("me", text)
        else:
            await notice.edit(text)

        try:
            loader_mod = self.lookup("loader")
            if loader_mod and hasattr(loader_mod, "download_and_install"):
                await loader_mod.download_and_install(url, None)
            else:
                await self._client.send_message(
                    "me", f"{self.get_prefix()}dlmod {url}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Self-update failed: %s", exc)
            await notice.edit(self.strings("self_fail").format(exc))
            return False

        # сообщение об успехе (на случай, если loader не покажет своё)
        try:
            await notice.edit(self.strings("self_updated").format(new_str))
        except Exception:  # noqa: BLE001
            pass
        return True

    @loader.loop(interval=3600, autostart=True)
    async def _self_update_loop(self):
        if not self.config["auto_update"]:
            return
        # уважаем update_interval (в часах), а тикаем раз в час
        last = self._db.get(self.strings["name"], "last_self_check", 0)
        interval = int(self.config["update_interval"]) * 3600
        if time.time() - last < interval:
            return
        self._db.set(self.strings["name"], "last_self_check", int(time.time()))
        try:
            await self._check_self_update(reply=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Self-update loop error: %s", exc)

    # ───────────────────── установка модулей ─────────────────────
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
