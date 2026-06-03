__version__ = (1, 5, 4)

# meta developer: @dragomodules
# scope: heroku_only
# requires: telethon aiohttp
# changelog: маркер «выкл» ▫️ вместо громоздкого ⬜️ в меню автообновления

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoModUpdates — установка модулей из канала в один тап.     ║
# ║  Работает в паре с ботом-витриной модулей. Умеет обновлять     ║
# ║  сам себя из репозитория.                                      ║
# ╚══════════════════════════════════════════════════════════════╝

import inspect
import json
import logging
import re
import sys
import time

import aiohttp
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)

# Должно совпадать с INSTALL_MARKER в боте (bot/handlers/user.py)
INSTALL_MARKER = "#HerokuModInstall"

# репозиторий модулей DragoModules
_REPO = "firedragoq/heroku-modules"
_REPO_API = f"https://api.github.com/repos/{_REPO}/contents/modules?ref=main"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/main/modules"

# Версия запущенного модуля — для сравнения с версией в репозитории
SELF_VERSION = __version__

_VERSION_RE = re.compile(r"__version__\s*=\s*\(([^)]+)\)")
_CHANGELOG_RE = re.compile(r"#\s*changelog\s*:\s*(.+)", re.IGNORECASE)


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


def _parse_changelog(text: str) -> str:
    """Достаёт строку '# changelog:' из исходника модуля."""
    m = _CHANGELOG_RE.search(text)
    return m.group(1).strip() if m else ""


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
        "au_status": (
            "♻️ <b>Автообновление модулей DragoModules</b>\n\n"
            "Глобально: <b>{glob}</b>\n"
            "Интервал проверки: раз в <b>{iv} ч</b>\n"
            "Установлено из репозитория: <b>{n}</b>\n"
            "{disabled}\n\n"
            "<code>{p}autoupd on</code> / <code>{p}autoupd off</code> — вкл/выкл всё\n"
            "<code>{p}autoupd ИмяМодуля</code> — переключить конкретный\n"
            "<code>{p}updateall</code> — проверить и обновить сейчас"
        ),
        "au_none_disabled": "Отключённых модулей нет.",
        "au_disabled_list": "Отключены: {list}",
        "au_on": "✅ <b>Автообновление модулей включено.</b>",
        "au_off": "⛔ <b>Автообновление модулей выключено.</b>",
        "au_mod_on": "✅ <b>{name}</b> — автообновление <b>включено</b>.",
        "au_mod_off": "⛔ <b>{name}</b> — автообновление <b>выключено</b>.",
        "au_not_found": "🚫 <b>Модуль</b> <code>{}</code> <b>не найден среди установленных.</b>",
        "all_checking": "♻️ <b>Проверяю обновления модулей…</b>",
        "all_done": "✅ <b>Обновлено модулей: {n}</b>\n{list}",
        "all_uptodate": "✅ <b>Все модули DragoModules актуальны.</b>",
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
                "auto_update_all",
                True,
                "Автоматически обновлять ВСЕ установленные модули DragoModules "
                "из репозитория (отдельные можно отключить через .autoupd <имя>).",
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
        changelog = _parse_changelog(source)
        text = self.strings("self_updating").format(old=cur_str, new=new_str)
        if changelog:
            text += "\n\n🔥 <b>Что нового:</b>\n" + utils.escape_html(changelog)
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
        success = self.strings("self_updated").format(new_str)
        if changelog:
            success += "\n\n🔥 <b>Что нового:</b>\n" + utils.escape_html(changelog)
        try:
            await notice.edit(success)
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

    # ───────────── автообновление выбранных модулей (opt-in) ─────────────
    def _enabled(self) -> list:
        """Список модулей, выбранных для автообновления (по умолчанию пусто)."""
        return self._db.get(self.strings["name"], "au_enabled", [])

    def _set_enabled(self, names: list):
        self._db.set(self.strings["name"], "au_enabled", sorted(set(names)))

    @staticmethod
    def _mod_version(mod):
        """Версия загруженного модуля как кортеж чисел (или None)."""
        v = getattr(mod, "__version__", None) or getattr(mod, "version", None)
        if v is None:  # из модуля, где определён класс
            try:
                m = inspect.getmodule(type(mod))
            except Exception:  # noqa: BLE001
                m = sys.modules.get(getattr(type(mod), "__module__", ""), None)
            v = getattr(m, "__version__", None) if m else None
        try:
            if isinstance(v, (tuple, list)):
                return tuple(int(x) for x in v)
            if isinstance(v, str):
                return tuple(int(x) for x in v.split(".") if x.isdigit())
        except Exception:  # noqa: BLE001
            return None
        return None

    def _installed_db(self) -> dict:
        return self._db.get(self.strings["name"], "installed_versions", {})

    def _record_version(self, name: str, ver):
        d = self._installed_db()
        d[name] = list(ver)
        self._db.set(self.strings["name"], "installed_versions", d)

    async def _repo_modules(self) -> list:
        """Список имён модулей в репозитории (без .py)."""
        data = json.loads(await self._fetch(_REPO_API))
        return [
            item["name"][:-3]
            for item in data
            if isinstance(item, dict)
            and item.get("type") == "file"
            and item.get("name", "").endswith(".py")
        ]

    async def _installed_drago(self) -> list:
        """Установленные модули, которые есть в репозитории (имена, отсортированы)."""
        names = await self._repo_modules()
        return sorted(
            n for n in names
            if n != self.strings["name"] and self.lookup(n) is not None
        )

    async def _check_all_updates(self, only: list = None) -> list:
        """Обновляет выбранные (only) модули, если в репо версия новее.

        Возвращает список (имя, старая, новая). Сообщения не шлёт — это делает вызвавший.
        """
        targets = list(only) if only is not None else self._enabled()
        updated = []
        for name in targets:
            if name == self.strings["name"]:
                continue  # сам себя обновляет отдельный loop
            mod = self.lookup(name)
            if mod is None:
                continue  # не установлен
            local = self._mod_version(mod)
            if local is None:  # не прочиталась — берём из нашей записи
                rec = self._installed_db().get(name)
                local = tuple(rec) if rec else None
            url = f"{_RAW_BASE}/{name}.py?t={int(time.time())}"
            try:
                src = await self._fetch(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fetch %s failed: %s", name, exc)
                continue
            remote = _parse_version(src)
            if not remote or (local and remote <= local):
                continue
            try:
                await self._do_install(url)
                self._record_version(name, remote)
                updated.append(
                    (name, ".".join(map(str, local or ())) or "?",
                     ".".join(map(str, remote)))
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("update %s failed: %s", name, exc)
        return updated

    def _fmt_updated(self, updated: list) -> str:
        if not updated:
            return self.strings("all_uptodate")
        lst = "\n".join(
            f"• <b>{n}</b> <code>v{o}</code> → <code>v{r}</code>" for n, o, r in updated
        )
        return self.strings("all_done").format(n=len(updated), list=lst)

    async def _do_install(self, url: str):
        """Тихая установка/обновление по ссылке."""
        loader_mod = self.lookup("loader")
        if loader_mod and hasattr(loader_mod, "download_and_install"):
            await loader_mod.download_and_install(url, None)
        else:
            await self._client.send_message("me", f"{self.get_prefix()}dlmod {url}")

    @loader.loop(interval=3600, autostart=True)
    async def _update_all_loop(self):
        if not self.config["auto_update_all"]:
            return
        if not self._enabled():
            return  # ничего не выбрано — нечего проверять
        last = self._db.get(self.strings["name"], "last_all_check", 0)
        interval = int(self.config["update_interval"]) * 3600
        if time.time() - last < interval:
            return
        self._db.set(self.strings["name"], "last_all_check", int(time.time()))
        try:
            updated = await self._check_all_updates()
            if updated:
                await self._client.send_message("me", self._fmt_updated(updated))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Update-all loop error: %s", exc)

    # ── инлайн-меню выбора модулей ──
    async def _autoupd_rows(self):
        installed = await self._installed_drago()
        enabled = set(self._enabled())
        rows, row = [], []
        for n in installed:
            mark = "✅" if n in enabled else "▫️"
            row.append({
                "text": f"{mark} {n}",
                "callback": self._au_toggle,
                "args": (n,),
            })
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        if not installed:
            rows.append([{"text": "Нет установленных модулей", "action": "close"}])
        rows.append([
            {"text": "🔄 Обновить выбранные", "callback": self._au_update_now},
            {"text": "❌ Закрыть", "action": "close"},
        ])
        return rows

    # заголовок шлёт инлайн-бот → премиум-эмодзи в формате Bot API <tg-emoji>
    _AU_TITLE = (
        '<tg-emoji emoji-id="5260375398956442465">🔄</tg-emoji> '
        "<b>Автообновление модулей DragoModules</b>\n\n"
        "Отметь модули, которые обновлять автоматически "
        '(<tg-emoji emoji-id="5258387825530807373">✅</tg-emoji>).\n'
        "По умолчанию выключено для всех."
    )

    async def _au_toggle(self, call, name):
        enabled = self._enabled()
        if name in enabled:
            enabled.remove(name)
        else:
            enabled.append(name)
        self._set_enabled(enabled)
        await call.edit(self._AU_TITLE, reply_markup=await self._autoupd_rows())

    async def _au_update_now(self, call):
        await call.edit(
            '<tg-emoji emoji-id="5260375398956442465">🔄</tg-emoji> '
            "<b>Проверяю выбранные модули…</b>"
        )
        updated = await self._check_all_updates()
        await call.edit(self._fmt_updated(updated))

    @loader.command(ru_doc="Меню автообновления модулей (кнопки)", alias="autoupdate")
    async def autoupdcmd(self, message: Message):
        """[module] — auto-update menu / toggle a module"""
        arg = utils.get_args_raw(message).strip()
        if arg:  # переключить конкретный модуль текстом (без инлайна)
            mod = self.lookup(arg)
            name = mod.strings["name"] if (mod and getattr(mod, "strings", None)) else arg
            if mod is None:
                return await utils.answer(
                    message, self.strings("au_not_found").format(utils.escape_html(arg))
                )
            enabled = self._enabled()
            if name in enabled:
                enabled.remove(name)
                self._set_enabled(enabled)
                return await utils.answer(
                    message, self.strings("au_mod_off").format(name=utils.escape_html(name))
                )
            enabled.append(name)
            self._set_enabled(enabled)
            return await utils.answer(
                message, self.strings("au_mod_on").format(name=utils.escape_html(name))
            )

        if not getattr(self, "inline", None):
            # без инлайна — текстовый список
            installed = await self._installed_drago()
            enabled = set(self._enabled())
            lines = ["♻️ <b>Автообновление модулей</b>\n"]
            for n in installed:
                mark = "✅" if n in enabled else "⬜️"
                lines.append(f"{mark} <code>{n}</code>")
            lines.append(
                f"\nПереключить: <code>{self.get_prefix()}autoupd ИмяМодуля</code>"
            )
            return await utils.answer(message, "\n".join(lines))
        await self.inline.form(
            message=message,
            text=self._AU_TITLE,
            reply_markup=await self._autoupd_rows(),
        )

    @loader.command(ru_doc="Обновить выбранные модули сейчас", alias="updall")
    async def updateallcmd(self, message: Message):
        """Update selected DragoModules now"""
        if not self._enabled():
            return await utils.answer(
                message,
                "ℹ️ <b>Ни один модуль не выбран для автообновления.</b>\n"
                f"Открой меню: <code>{self.get_prefix()}autoupd</code>",
            )
        msg = await utils.answer(message, self.strings("all_checking"))
        updated = await self._check_all_updates()
        await utils.answer(msg, self._fmt_updated(updated))

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
