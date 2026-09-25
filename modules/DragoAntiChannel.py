__version__ = (1, 1, 0)

# meta developer: @dragomodules
# meta category: Модерация
# scope: heroku_only
# requires: telethon
# changelog: фильтр по никам (.acname) — удаляет сообщения юзеров со спам-ником, пока не сменят

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoAntiChannel — чистит сообщения «от имени канала»       ║
# ║  и юзеров со спам-ником в указанных чатах.                   ║
# ║  .acwatch — следить · .acchats — список ·                    ║
# ║  .acwl — белый список каналов · .acname — фильтр ников.      ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging

from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Message, PeerChannel
from telethon.utils import get_display_name, get_peer_id

from .. import loader, utils

logger = logging.getLogger(__name__)

# премиум-иконки (набор @vpnfiredragoq_bot); для не-Premium показывается фоллбэк
PE_LOCK = "<emoji document_id=5258244463817433519>🔒</emoji>"
PE_STOP = "<emoji document_id=5260319946633681748>🛑</emoji>"
PE_OK = "<emoji document_id=5258387825530807373>✅</emoji>"
PE_LINK = "<emoji document_id=5258407500775989445>🔗</emoji>"
PE_WARN = "<emoji document_id=5260644989758640758>⚠️</emoji>"


@loader.tds
class DragoAntiChannelMod(loader.Module):
    """🔒 Удаляет сообщения «от имени канала» и юзеров со спам-ником в выбранных чатах."""

    strings = {
        "name": "DragoAntiChannel",
        "not_group": f"{PE_WARN} <b>Команду нужно вызывать в группе.</b>",
        "watch_on": (
            f"{PE_OK} <b>Слежу за этим чатом.</b> Сообщения «от имени канала» "
            "буду удалять.\n<code>{id}</code>"
        ),
        "watch_off": f"{PE_STOP} <b>Перестал следить за этим чатом.</b>\n<code>{{id}}</code>",
        "chats_empty": (
            f"{PE_LOCK} <b>Список пуст.</b> Зайди в нужный чат и вызови "
            "<code>{p}acwatch</code>."
        ),
        "chats_head": f"{PE_LOCK} <b>Слежу за чатами ({{n}}):</b>\n{{rows}}",
        "chats_foot": "\n\n{PE_STOP} Удалено сообщений: <b>{count}</b>",
        "wl_empty": (
            f"{PE_WARN} <b>Укажи канал.</b> Ответь на его сообщение командой "
            "<code>{p}acwl</code> или передай ID: <code>{p}acwl -100…</code>"
        ),
        "wl_on": f"{PE_OK} <b>Канал в белом списке.</b> Его не трогаю.\n<code>{{id}}</code>",
        "wl_off": f"{PE_STOP} <b>Канал убран из белого списка.</b>\n<code>{{id}}</code>",
        "wl_list": f"{PE_OK} <b>Белый список ({{n}}):</b>\n{{rows}}",
        "deleted": f"{PE_STOP} <b>Удалил сообщение от имени канала</b> <i>{{name}}</i>",
        "deleted_name": f"{PE_STOP} <b>Удалил сообщение</b> — ник <i>{{name}}</i> в фильтре.",
        "name_list": f"{PE_LOCK} <b>Фильтр ников ({{n}}):</b>\n{{rows}}",
        "name_empty": (
            f"{PE_WARN} <b>Фильтр ников пуст.</b> Добавь слово: "
            "<code>{p}acname физы</code> (или ответь на спамера командой <code>{p}acname</code>)."
        ),
        "name_added": (
            f"{PE_OK} <b>Добавил в фильтр ников:</b> <code>{{phrase}}</code>\n"
            "Сообщения с таким ником удаляю, пока не сменит."
        ),
        "name_exists": f"{PE_WARN} <b>Уже в фильтре:</b> <code>{{phrase}}</code>",
        "name_removed": f"{PE_STOP} <b>Убрал из фильтра ников:</b> <code>{{phrase}}</code>",
        "name_not_found": f"{PE_WARN} <b>Такого нет в фильтре:</b> <code>{{phrase}}</code>",
        "name_need_arg": f"{PE_WARN} <b>Укажи слово:</b> <code>{{p}}acnamedel физы</code>",
    }

    strings_ru = {
        "_cls_doc": "🔒 Удаляет сообщения «от имени канала» и юзеров со спам-ником в выбранных чатах.",
        "acwatchcmd_doc": "вкл/выкл слежение за текущим чатом",
        "acchatscmd_doc": "список чатов под наблюдением",
        "acwlcmd_doc": "[реплай/ID] — добавить/убрать канал из белого списка",
        "acnamecmd_doc": "[реплай/слово] — добавить слово в фильтр ников (без слова — список)",
        "acnamedelcmd_doc": "<слово> — убрать слово из фильтра ников",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "delete",
                True,
                "Удалять сообщения. Если выкл — модуль только логирует, ничего не трёт.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "ignore_linked",
                True,
                "Не трогать репосты привязанного к группе канала (обсуждения).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "ignore_anon_admins",
                True,
                "Не трогать анонимных админов (пишут от имени самой группы).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "notify",
                False,
                "Слать в чат самоудаляющееся уведомление об удалении.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "notify_ttl",
                5,
                "Через сколько секунд убирать уведомление.",
                validator=loader.validators.Integer(minimum=2, maximum=60),
            ),
            loader.ConfigValue(
                "filter_names",
                True,
                "Фильтр по никам: удалять сообщения юзеров со спам-словом в нике.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "name_filters",
                [],
                "Слова-фильтры для ников (регистр не важен). Правится тут или командой .acname.",
                validator=loader.validators.Series(validator=loader.validators.String()),
            ),
        )
        self._linked_cache: dict = {}

    # ── helpers ──────────────────────────────────────────────────────────

    async def _linked_id(self, chat) -> int | None:
        """Marked-id привязанного канала группы (с кешем)."""
        key = chat.id
        if key in self._linked_cache:
            return self._linked_cache[key]
        linked = None
        try:
            full = await self._client(GetFullChannelRequest(chat))
            raw = getattr(full.full_chat, "linked_chat_id", 0) or 0
            if raw:
                linked = get_peer_id(PeerChannel(raw))
        except Exception as exc:  # noqa: BLE001
            logger.debug("linked lookup failed: %s", exc)
        self._linked_cache[key] = linked
        return linked

    async def _notify_delete(self, chat_id: int, text: str):
        try:
            note = await self._client.send_message(chat_id, text)
            await asyncio.sleep(int(self.config["notify_ttl"]))
            await note.delete()
        except Exception:  # noqa: BLE001
            pass

    async def _punish(self, message: Message, chat_id: int, kind: str):
        """Удаляет сообщение (если delete вкл) + счётчик + опциональное уведомление."""
        if not self.config["delete"]:
            logger.info("DragoAntiChannel: совпадение (%s) в чате %s, delete=off", kind, chat_id)
            return
        await message.delete()
        self.set("deleted_count", int(self.get("deleted_count", 0)) + 1)
        if not self.config["notify"]:
            return
        try:
            sender = await message.get_sender()
            name = self._title(sender) if kind == "channel" else (get_display_name(sender) or "?")
        except Exception:  # noqa: BLE001
            name = "?"
        key = "deleted" if kind == "channel" else "deleted_name"
        asyncio.create_task(
            self._notify_delete(chat_id, self.strings(key).format(name=utils.escape_html(name)))
        )

    @staticmethod
    def _title(entity) -> str:
        return (
            getattr(entity, "title", None)
            or getattr(entity, "first_name", None)
            or "канал"
        )

    # ── commands ─────────────────────────────────────────────────────────

    @loader.command(ru_doc="вкл/выкл слежение за текущим чатом")
    async def acwatchcmd(self, message):
        """toggle monitoring of the current chat"""
        if message.is_private:
            return await utils.answer(message, self.strings("not_group"))
        chat_id = utils.get_chat_id(message)
        chats = list(self.get("chats", []))
        if chat_id in chats:
            chats.remove(chat_id)
            self.set("chats", chats)
            return await utils.answer(message, self.strings("watch_off").format(id=chat_id))
        chats.append(chat_id)
        self.set("chats", chats)
        await utils.answer(message, self.strings("watch_on").format(id=chat_id))

    @loader.command(ru_doc="список чатов под наблюдением")
    async def acchatscmd(self, message):
        """list monitored chats"""
        chats = list(self.get("chats", []))
        if not chats:
            return await utils.answer(
                message, self.strings("chats_empty").format(p=self.get_prefix())
            )
        rows = []
        for cid in chats:
            try:
                ent = await self._client.get_entity(cid)
                title = utils.escape_html(self._title(ent))
            except Exception:  # noqa: BLE001
                title = "?"
            rows.append(f"{PE_LINK} {title} (<code>{cid}</code>)")
        text = self.strings("chats_head").format(n=len(chats), rows="\n".join(rows))
        text += self.strings("chats_foot").format(
            PE_STOP=PE_STOP, count=int(self.get("deleted_count", 0))
        )
        await utils.answer(message, text)

    @loader.command(ru_doc="[реплай/ID] — добавить/убрать канал из белого списка")
    async def acwlcmd(self, message):
        """[reply/ID] — toggle channel in the whitelist"""
        target = None
        reply = await message.get_reply_message()
        if reply is not None and isinstance(getattr(reply, "from_id", None), PeerChannel):
            target = reply.sender_id
        else:
            arg = (utils.get_args_raw(message) or "").strip()
            if arg:
                try:
                    target = int(arg)
                except ValueError:
                    target = None

        wl = list(self.get("whitelist", []))
        if target is None:
            if not wl:
                return await utils.answer(
                    message, self.strings("wl_empty").format(p=self.get_prefix())
                )
            rows = "\n".join(f"{PE_LINK} <code>{c}</code>" for c in wl)
            return await utils.answer(
                message, self.strings("wl_list").format(n=len(wl), rows=rows)
            )

        if target in wl:
            wl.remove(target)
            self.set("whitelist", wl)
            return await utils.answer(message, self.strings("wl_off").format(id=target))
        wl.append(target)
        self.set("whitelist", wl)
        await utils.answer(message, self.strings("wl_on").format(id=target))

    @loader.command(ru_doc="[реплай/слово] — добавить слово в фильтр ников (без слова — список)")
    async def acnamecmd(self, message):
        """[reply/word] — add a word to the nickname filter (no arg — list)"""
        phrase = (utils.get_args_raw(message) or "").strip()
        if not phrase:
            reply = await message.get_reply_message()
            if reply is not None:
                sender = await reply.get_sender()
                if sender is not None:
                    phrase = (get_display_name(sender) or "").strip()
        phrase = phrase.lower()

        filters = list(self.config["name_filters"])
        if not phrase:
            if not filters:
                return await utils.answer(
                    message, self.strings("name_empty").format(p=self.get_prefix())
                )
            rows = "\n".join(
                f"{PE_LINK} <code>{utils.escape_html(f)}</code>" for f in filters
            )
            return await utils.answer(
                message, self.strings("name_list").format(n=len(filters), rows=rows)
            )

        if phrase in filters:
            return await utils.answer(
                message, self.strings("name_exists").format(phrase=utils.escape_html(phrase))
            )
        filters.append(phrase)
        self.config["name_filters"] = filters
        await utils.answer(
            message, self.strings("name_added").format(phrase=utils.escape_html(phrase))
        )

    @loader.command(ru_doc="<слово> — убрать слово из фильтра ников")
    async def acnamedelcmd(self, message):
        """<word> — remove a word from the nickname filter"""
        phrase = (utils.get_args_raw(message) or "").strip().lower()
        if not phrase:
            return await utils.answer(
                message, self.strings("name_need_arg").format(p=self.get_prefix())
            )
        filters = list(self.config["name_filters"])
        if phrase not in filters:
            return await utils.answer(
                message, self.strings("name_not_found").format(phrase=utils.escape_html(phrase))
            )
        filters.remove(phrase)
        self.config["name_filters"] = filters
        await utils.answer(
            message, self.strings("name_removed").format(phrase=utils.escape_html(phrase))
        )

    # ── watcher ──────────────────────────────────────────────────────────

    @loader.watcher()
    async def watcher(self, message: Message):
        try:
            chat_id = utils.get_chat_id(message)
            if chat_id not in self.get("chats", []):
                return

            # 1) фильтр по никам (любой пользователь, кроме себя)
            if (
                self.config["filter_names"]
                and not getattr(message, "out", False)
                and await self._name_hit(message)
            ):
                return await self._punish(message, chat_id, "name")

            # 2) сообщения «от имени канала»
            from_id = getattr(message, "from_id", None)
            if not isinstance(from_id, PeerChannel):
                return

            sender_id = message.sender_id

            # анонимный админ группы пишет от имени самой группы
            if sender_id == chat_id and self.config["ignore_anon_admins"]:
                return

            if sender_id in self.get("whitelist", []):
                return

            if self.config["ignore_linked"]:
                chat = await message.get_chat()
                if sender_id == await self._linked_id(chat):
                    return

            await self._punish(message, chat_id, "channel")
        except Exception as exc:  # noqa: BLE001 — вотчер не должен падать
            logger.debug("DragoAntiChannel watcher error: %s", exc)

    async def _name_hit(self, message: Message) -> bool:
        """True, если ник отправителя содержит слово из фильтра."""
        filters = self.config["name_filters"]
        if not filters:
            return False
        try:
            sender = await message.get_sender()
        except Exception:  # noqa: BLE001
            return False
        if sender is None:
            return False
        sid = getattr(sender, "id", None)
        if sid == self._tg_id or sid in self.get("whitelist", []):
            return False
        name = (get_display_name(sender) or "").lower()
        if not name:
            return False
        return any(f in name for f in filters)
