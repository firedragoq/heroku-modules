__version__ = (1, 1, 0)

# meta developer: @dragomodules
# meta category: Безопасность
# scope: heroku_only
# requires: telethon
# changelog: команды под @dragomodules — .dpm/.dpmallow/.dpmlast (старые pmbl/allowpm/pmbanlast остались алиасами)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoPMBL — страж лички. Банит и репортит незнакомцев,      ║
# ║  которые пишут первыми, до одобрения.                        ║
# ║  .dpm — вкл/выкл · .dpmallow — впустить в ЛС ·               ║
# ║  .dpmlast N — снести N последних диалогов после рейда.       ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Идея и оригинал: PM->BL © hikariatama (AGPLv3). Форк под @dragomodules.

import contextlib
import logging
import time
from typing import Optional

from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest, ReportSpamRequest
from telethon.tl.types import Message, PeerUser, User
from telethon.utils import get_display_name, get_peer_id

from .. import loader, utils

logger = logging.getLogger(__name__)

# премиум-иконки (набор @vpnfiredragoq_bot); для не-Premium показывается фоллбэк
PE_SHIELD = "<emoji document_id=5258244463817433519>🔒</emoji>"
PE_STOP = "<emoji document_id=5260319946633681748>🛑</emoji>"
PE_OK = "<emoji document_id=5258387825530807373>✅</emoji>"
PE_WARN = "<emoji document_id=5260644989758640758>⚠️</emoji>"
PE_LINK = "<emoji document_id=5258407500775989445>🔗</emoji>"


def _yn(state: Optional[bool]) -> str:
    if state is None:
        return "❔"
    return "✅ да" if state else "🚫 нет"


@loader.tds
class DragoPMBLMod(loader.Module):
    """🔒 Банит и репортит входящие сообщения от незнакомцев."""

    strings = {
        "name": "DragoPMBL",
        "state": (
            f"{PE_SHIELD} <b>DragoPMBL теперь {{}}</b>\n"
            "<i>Репорт спама — {}\nУдалять диалог — {}</i>"
        ),
        "args_pmban": (
            f"{PE_WARN} <b>Пример:</b> <code>{{p}}dpmlast 5</code>"
        ),
        "banned": (
            "🛡 <b>Привет •ᴗ•</b>\n"
            "<b>Страж</b> этого аккаунта на связи. Ты <b>ещё не одобрен</b>, "
            "поэтому из соображений безопасности я вынужден тебя заблокировать.\n"
            "Если нужна помощь — напиши владельцу <b>в общий чат</b>."
        ),
        "removing": f"{PE_STOP} <b>Удаляю {{}} последних диалогов…</b>",
        "removed": f"{PE_OK} <b>Готово, снёс {{}} последних диалогов.</b>",
        "user_not_specified": f"{PE_WARN} <b>Не указан пользователь.</b>",
        "approved": (
            f"{PE_OK} <b><a href=\"tg://user?id={{}}\">{{}}</a> впущен в ЛС.</b>"
        ),
        "banned_log": (
            f"{PE_STOP} <b>Заблокировал <a href=\"tg://user?id={{}}\">{{}}</a>.</b>\n\n"
            "<b>{} Репорт спама</b>\n<b>{} Удалён диалог</b>\n\n"
            "<b>📝 Сообщение:</b>\n<code>{}</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "🔒 Банит и репортит входящие сообщения от незнакомцев.",
        "dpmcmd_doc": "включить или выключить защиту",
        "dpmlastcmd_doc": "<N> — забанить и снести N последних диалогов",
        "dpmallowcmd_doc": "<реплай/юзер> — впустить пользователя в ЛС",
    }

    def __init__(self):
        self._queue = []
        self._ban_queue = []
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "ignore_contacts",
                True,
                lambda: "Игнорировать контакты?",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "ignore_active",
                True,
                lambda: "Игнорировать диалоги, где ты уже активно писал?",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "active_threshold",
                5,
                lambda: "Сколько твоих сообщений нужно, чтобы доверять собеседнику.",
                validator=loader.validators.Integer(minimum=1),
            ),
            loader.ConfigValue(
                "custom_message",
                "",
                lambda: "Своё сообщение бану. Пусто — берётся стандартное.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "photo",
                "",
                lambda: "Картинка к уведомлению о бане. Пусто — только текст.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "report_spam",
                False,
                lambda: "Репортить спам при бане?",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "delete_dialog",
                False,
                lambda: "Удалять диалог при бане?",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "silent",
                False,
                lambda: "Ничего не отправлять забаненному.",
                validator=loader.validators.Boolean(),
            ),
        )

    async def client_ready(self):
        self._whitelist = self.get("whitelist", [])
        self._ratelimit = []
        self._ratelimit_timeout = 5 * 60
        self._ratelimit_threshold = 10

    @loader.command(ru_doc="включить или выключить защиту", alias="pmbl")
    async def dpmcmd(self, message: Message):
        """toggle protection"""
        new = not self.get("state", False)
        self.set("state", new)
        await utils.answer(
            message,
            self.strings("state").format(
                "включён 🟢" if new else "выключен 🔴",
                _yn(self.config["report_spam"]),
                _yn(self.config["delete_dialog"]),
            ),
        )

    @loader.command(ru_doc="<N> — забанить и снести N последних диалогов", alias="pmbanlast")
    async def dpmlastcmd(self, message: Message):
        """<N> — ban and delete dialogs with N newest users"""
        n = utils.get_args_raw(message)
        if not n or not n.isdigit():
            await utils.answer(
                message, self.strings("args_pmban").format(p=self.get_prefix())
            )
            return

        n = int(n)
        await utils.answer(message, self.strings("removing").format(n))

        dialogs = []
        async for dialog in self._client.iter_dialogs(ignore_pinned=True):
            try:
                if not isinstance(dialog.message.peer_id, PeerUser):
                    continue
            except AttributeError:
                continue

            m = (
                await self._client.get_messages(
                    dialog.message.peer_id,
                    limit=1,
                    reverse=True,
                )
            )[0]

            dialogs += [
                (
                    get_peer_id(dialog.message.peer_id),
                    int(time.mktime(m.date.timetuple())),
                )
            ]

        dialogs.sort(key=lambda x: x[1])
        to_ban = [d for d, _ in dialogs[::-1][:n]]

        for d in to_ban:
            await self._client(BlockRequest(id=d))
            await self._client(DeleteHistoryRequest(peer=d, just_clear=True, max_id=0))

        await utils.answer(message, self.strings("removed").format(len(to_ban)))

    def _approve(self, user: int, reason: str = "unknown"):
        self._whitelist += [user]
        self._whitelist = list(set(self._whitelist))
        self.set("whitelist", self._whitelist)
        logger.debug("User approved in pm %s, filter: %s", user, reason)

    @loader.command(ru_doc="<реплай/юзер> — впустить пользователя в ЛС", alias="allowpm")
    async def dpmallowcmd(self, message: Message):
        """<reply/user> — allow user to pm you"""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()

        user = None
        try:
            user = await self._client.get_entity(args)
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                user = await self._client.get_entity(reply.sender_id) if reply else None

        if not user:
            chat = await message.get_chat()
            if not isinstance(chat, User):
                await utils.answer(message, self.strings("user_not_specified"))
                return
            user = chat

        self._approve(user.id, "manual_approve")
        await utils.answer(
            message, self.strings("approved").format(user.id, get_display_name(user))
        )

    @loader.watcher()
    async def watcher(self, message: Message):
        if (
            getattr(message, "out", False)
            or not isinstance(message, Message)
            or not isinstance(message.peer_id, PeerUser)
            or not self.get("state", False)
            or utils.get_chat_id(message)
            in {
                1271266957,  # @replies
                777000,  # Telegram Notifications
                self._tg_id,  # сам аккаунт
            }
        ):
            return

        self._queue += [message]

    @loader.loop(interval=0.05, autostart=True)
    async def ban_loop(self):
        if not self._ban_queue:
            return

        message = self._ban_queue.pop(0)
        self._ratelimit = list(
            filter(
                lambda x: x + self._ratelimit_timeout < time.time(),
                self._ratelimit,
            )
        )

        dialog = None
        notify_text = self.config["custom_message"] or self.strings("banned")

        if len(self._ratelimit) < self._ratelimit_threshold:
            if not self.config["silent"]:
                photo = self.config["photo"]
                try:
                    if photo:
                        await self._client.send_file(
                            message.peer_id, photo, caption=notify_text
                        )
                    else:
                        await self._client.send_message(message.peer_id, notify_text)
                except Exception:  # noqa: BLE001
                    with contextlib.suppress(Exception):
                        await self._client.send_message(message.peer_id, notify_text)

                self._ratelimit += [round(time.time())]

            with contextlib.suppress(ValueError):
                dialog = await self._client.get_entity(message.peer_id)

        await self.inline.bot.send_message(
            self._client.tg_id,
            self.strings("banned_log").format(
                dialog.id if dialog is not None else message.sender_id,
                (
                    utils.escape_html(dialog.first_name)
                    if dialog is not None
                    else (
                        getattr(getattr(message, "sender", None), "username", None)
                        or message.sender_id
                    )
                ),
                _yn(self.config["report_spam"]),
                _yn(self.config["delete_dialog"]),
                utils.escape_html(
                    "<стикер>"
                    if message.sticker
                    else (
                        "<фото>"
                        if message.photo
                        else (
                            "<видео>"
                            if message.video
                            else (
                                "<файл>"
                                if message.document
                                else message.raw_text[:3000]
                            )
                        )
                    )
                ),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        await self._client(BlockRequest(id=message.sender_id))

        if self.config["report_spam"]:
            await self._client(ReportSpamRequest(peer=message.sender_id))

        if self.config["delete_dialog"]:
            await self._client(
                DeleteHistoryRequest(peer=message.sender_id, just_clear=True, max_id=0)
            )

        self._approve(message.sender_id, "banned")
        logger.warning("Intruder punished: %s", message.sender_id)

    @loader.loop(interval=0.01, autostart=True)
    async def queue_processor(self):
        if not self._queue:
            return

        message = self._queue.pop(0)

        cid = utils.get_chat_id(message)
        if cid in self._whitelist:
            return

        peer = (
            getattr(getattr(message, "sender", None), "username", None)
            or message.peer_id
        )

        with contextlib.suppress(ValueError):
            entity = await self._client.get_entity(peer)

            if entity.bot:
                return self._approve(cid, "bot")

            if self.config["ignore_contacts"] and entity.contact:
                return self._approve(cid, "ignore_contacts")

        first_message = (
            await self._client.get_messages(
                peer,
                limit=1,
                reverse=True,
            )
        )[0]

        if (
            getattr(message, "raw_text", False)
            and first_message.sender_id == self._tg_id
        ):
            return self._approve(cid, "started_by_you")

        if self.config["ignore_active"]:
            q = 0
            async for msg in self._client.iter_messages(peer, limit=200):
                if msg.sender_id == self._tg_id:
                    q += 1
                if q >= self.config["active_threshold"]:
                    return self._approve(cid, "active_threshold")

        self._ban_queue += [message]

    @loader.debug_method(name="dpmdeny")
    async def denypm(self, message: Message):
        user = (await message.get_reply_message()).sender_id
        self.set("whitelist", list(set(self.get("whitelist", [])) - {user}))
        return f"User unwhitelisted: {user}"
