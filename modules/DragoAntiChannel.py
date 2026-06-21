__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Модерация
# scope: heroku_only
# requires: telethon
# changelog: первый релиз — удаление сообщений «от имени канала» в выбранных чатах

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoAntiChannel — чистит сообщения, отправленные «как канал» ║
# ║  (Send as channel), в указанных чатах. Реклама-каналы мимо.    ║
# ║  .acwatch — следить за чатом · .acchats — список ·             ║
# ║  .acwl — белый список каналов-исключений.                     ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging

from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Message, PeerChannel
from telethon.utils import get_peer_id

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
    """🔒 Удаляет сообщения, отправленные «от имени канала», в выбранных чатах."""

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
    }

    strings_ru = {
        "_cls_doc": "🔒 Удаляет сообщения, отправленные «от имени канала», в выбранных чатах.",
        "acwatchcmd_doc": "вкл/выкл слежение за текущим чатом",
        "acchatscmd_doc": "список чатов под наблюдением",
        "acwlcmd_doc": "[реплай/ID] — добавить/убрать канал из белого списка",
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

    async def _notify_delete(self, chat_id: int, name: str):
        try:
            note = await self._client.send_message(
                chat_id, self.strings("deleted").format(name=utils.escape_html(name))
            )
            await asyncio.sleep(int(self.config["notify_ttl"]))
            await note.delete()
        except Exception:  # noqa: BLE001
            pass

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

    # ── watcher ──────────────────────────────────────────────────────────

    @loader.watcher()
    async def watcher(self, message: Message):
        try:
            from_id = getattr(message, "from_id", None)
            if not isinstance(from_id, PeerChannel):
                return  # обычный пользователь — не наш случай

            chat_id = utils.get_chat_id(message)
            if chat_id not in self.get("chats", []):
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

            if not self.config["delete"]:
                logger.info("DragoAntiChannel: канал %s в чате %s (delete=off)", sender_id, chat_id)
                return

            await message.delete()
            self.set("deleted_count", int(self.get("deleted_count", 0)) + 1)

            if self.config["notify"]:
                sender = await message.get_sender()
                asyncio.create_task(
                    self._notify_delete(chat_id, self._title(sender))
                )
        except Exception as exc:  # noqa: BLE001 — вотчер не должен падать
            logger.debug("DragoAntiChannel watcher error: %s", exc)
