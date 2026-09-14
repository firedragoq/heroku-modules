__version__ = (1, 4, 0)

# meta developer: @dragomodules
# meta category: Безопасность
# meta pic: https://raw.githubusercontent.com/firedragoq/heroku-modules/main/assets/DragoPMBL.jpg
# meta banner: https://raw.githubusercontent.com/firedragoq/heroku-modules/main/assets/DragoPMBL.jpg
# scope: heroku_only
# requires: telethon
# changelog: авто-разбан (auto_unblock) — пишешь в ЛС забаненному → он снимается из ЧС и одобряется

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
import re
import time
from typing import Optional

from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.messages import DeleteHistoryRequest, ReportSpamRequest
from telethon.tl.types import Message, PeerUser, User
from telethon.utils import get_display_name, get_peer_id

from .. import loader, utils

logger = logging.getLogger(__name__)

# премиум-иконки (набор @vpnfiredragoq_bot); дефолты для конфига, можно менять
PE_SHIELD = "<emoji document_id=5258244463817433519>🔒</emoji>"
PE_STOP = "<emoji document_id=5260319946633681748>🛑</emoji>"
PE_OK = "<emoji document_id=5258387825530807373>✅</emoji>"
PE_WARN = "<emoji document_id=5260644989758640758>⚠️</emoji>"
PE_LINK = "<emoji document_id=5258407500775989445>🔗</emoji>"


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна/бота)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )


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
            "{shield} <b>DragoPMBL теперь {state}</b>\n"
            "<i>Репорт спама — {rep}\nУдалять диалог — {dele}</i>"
        ),
        "args_pmban": "{warn} <b>Пример:</b> <code>{p}dpmlast 5</code>",
        "banned": (
            "{shield} <b>Привет •ᴗ•</b>\n"
            "<b>Страж</b> этого аккаунта на связи. Ты <b>ещё не одобрен</b>, "
            "поэтому из соображений безопасности я вынужден тебя заблокировать.\n"
            "Если нужна помощь — напиши владельцу <b>в общий чат</b>."
        ),
        "removing": "{ban} <b>Удаляю {n} последних диалогов…</b>",
        "removed": "{ok} <b>Готово, снёс {n} последних диалогов.</b>",
        "user_not_specified": "{warn} <b>Не указан пользователь.</b>",
        "approved": (
            '{ok} <b><a href="tg://user?id={uid}">{name}</a> впущен в ЛС.</b>'
        ),
        "forgotten": (
            '{ok} <b><a href="tg://user?id={uid}">{name}</a> забыт:</b> убран из памяти '
            "и разблокирован. Можно писать заново для теста."
        ),
        "reset": "{ok} <b>Память очищена.</b> Забыл записей: <b>{n}</b>.",
        "auto_unblocked": (
            '{ok} <b>Разблокировал <a href="tg://user?id={uid}">{name}</a></b> — '
            "ты написал ему в ЛС. Снял из ЧС и одобрил."
        ),
        "wl_empty": "{shield} <b>Память пуста</b> — никто ещё не обработан.",
        "wl_list": "{shield} <b>В памяти записей: {n}</b>\n{rows}",
        "banned_log": (
            '{ban} <b>Заблокировал <a href="tg://user?id={uid}">{name}</a>.</b>\n\n'
            "<b>{rep} Репорт спама</b>\n<b>{dele} Удалён диалог</b>\n\n"
            "<b>📝 Сообщение:</b>\n<code>{text}</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "🔒 Банит и репортит входящие сообщения от незнакомцев.",
        "dpmcmd_doc": "включить или выключить защиту",
        "dpmlastcmd_doc": "<N> — забанить и снести N последних диалогов",
        "dpmallowcmd_doc": "<реплай/юзер> — впустить пользователя в ЛС",
        "dpmforgetcmd_doc": "<реплай/id/@> — убрать из памяти и разбанить (для теста)",
        "dpmresetcmd_doc": "очистить всю память (вайтлист)",
        "dpmwlcmd_doc": "показать память (вайтлист)",
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
                "https://raw.githubusercontent.com/firedragoq/heroku-modules/main/assets/DragoPMBL_ban.jpg",
                lambda: "Картинка к уведомлению о бане (шлётся забаненному с текстом). Пусто — только текст.",
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
            loader.ConfigValue(
                "emoji_shield",
                PE_SHIELD,
                lambda: "Эмодзи-акцент «щит». Премиум (<emoji document_id=…>) или обычный.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_ok",
                PE_OK,
                lambda: "Эмодзи «ок». Премиум или обычный.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_ban",
                PE_STOP,
                lambda: "Эмодзи «бан/стоп». Премиум или обычный.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_warn",
                PE_WARN,
                lambda: "Эмодзи «предупреждение». Премиум или обычный.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                lambda: "Ответы команд — через инлайн-бота (от бота, а не аккаунта).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "auto_unblock",
                True,
                lambda: "Если сам пишешь в ЛС забаненному — авто-разбан и одобрение.",
                validator=loader.validators.Boolean(),
            ),
        )

    async def client_ready(self):
        self._whitelist = self.get("whitelist", [])
        self._banned = self.get("banned", [])  # кого заблокировал именно модуль
        self._ratelimit = []
        self._ratelimit_timeout = 5 * 60
        self._ratelimit_threshold = 10

    # ── helpers ──────────────────────────────────────────────────────────

    def _s(self, key: str, **kwargs) -> str:
        """Строка с автоподстановкой эмодзи из конфига + доп. плейсхолдеры."""
        return self.strings(key).format(
            shield=self.config["emoji_shield"],
            ok=self.config["emoji_ok"],
            ban=self.config["emoji_ban"],
            warn=self.config["emoji_warn"],
            **kwargs,
        )

    @property
    def _inline_on(self) -> bool:
        return bool(self.config["use_inline"]) and getattr(self, "inline", None) is not None

    async def _reply(self, message, text: str):
        if self._inline_on:
            try:
                return await self.inline.form(message=message, text=_to_bot_emoji(text))
            except Exception as exc:  # noqa: BLE001
                logger.warning("inline reply failed, fallback: %s", exc)
        return await utils.answer(message, text)

    async def _status(self, message, text: str):
        if self._inline_on:
            return message
        return await utils.answer(message, text)

    # ── commands ─────────────────────────────────────────────────────────

    @loader.command(ru_doc="включить или выключить защиту", alias="pmbl")
    async def dpmcmd(self, message: Message):
        """toggle protection"""
        new = not self.get("state", False)
        self.set("state", new)
        await self._reply(
            message,
            self._s(
                "state",
                state="включён 🟢" if new else "выключен 🔴",
                rep=_yn(self.config["report_spam"]),
                dele=_yn(self.config["delete_dialog"]),
            ),
        )

    @loader.command(ru_doc="<N> — забанить и снести N последних диалогов", alias="pmbanlast")
    async def dpmlastcmd(self, message: Message):
        """<N> — ban and delete dialogs with N newest users"""
        n = utils.get_args_raw(message)
        if not n or not n.isdigit():
            await self._reply(message, self._s("args_pmban", p=self.get_prefix()))
            return

        n = int(n)
        await self._status(message, self._s("removing", n=n))

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

        await self._reply(message, self._s("removed", n=len(to_ban)))

    def _set_whitelist(self, ids) -> None:
        """Единая точка записи памяти (вайтлиста): держим self._whitelist и БД в синхроне."""
        ids = list(set(ids))
        self._whitelist = ids
        self.set("whitelist", ids)

    def _set_banned(self, ids) -> None:
        """Память заблокированных модулем (для авто-разбана при ответе)."""
        ids = list(set(ids))
        self._banned = ids
        self.set("banned", ids)

    def _approve(self, user: int, reason: str = "unknown"):
        self._set_whitelist(self._whitelist + [user])
        logger.debug("User approved in pm %s, filter: %s", user, reason)

    async def _maybe_unblock_on_reply(self, message: Message) -> None:
        """Исходящее в ЛС забаненному → авто-разбан + одобрение."""
        if not self.config["auto_unblock"]:
            return
        peer_id = utils.get_chat_id(message)
        if peer_id not in self._banned:
            return

        self._set_banned([x for x in self._banned if x != peer_id])
        with contextlib.suppress(Exception):
            await self._client(UnblockRequest(id=peer_id))
        self._approve(peer_id, "owner_replied")

        name = str(peer_id)
        with contextlib.suppress(Exception):
            name = utils.escape_html(get_display_name(await self._client.get_entity(peer_id)))
        with contextlib.suppress(Exception):
            await self.inline.bot.send_message(
                self._client.tg_id,
                _to_bot_emoji(self._s("auto_unblocked", uid=peer_id, name=name)),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        logger.info("Auto-unblocked %s (owner replied)", peer_id)

    async def _resolve_user(self, message: Message):
        """Достаёт юзера из реплая / аргумента (id/@username) / текущего лс. None — если не вышло."""
        args = (utils.get_args_raw(message) or "").strip()
        reply = await message.get_reply_message()

        if args:
            with contextlib.suppress(Exception):
                target = int(args) if args.lstrip("-").isdigit() else args
                return await self._client.get_entity(target)

        if reply is not None:
            with contextlib.suppress(Exception):
                return await self._client.get_entity(reply.sender_id)

        chat = await message.get_chat()
        return chat if isinstance(chat, User) else None

    @loader.command(ru_doc="<реплай/юзер> — впустить пользователя в ЛС", alias="allowpm")
    async def dpmallowcmd(self, message: Message):
        """<reply/user> — allow user to pm you"""
        user = await self._resolve_user(message)
        if user is None:
            await self._reply(message, self._s("user_not_specified"))
            return

        self._approve(user.id, "manual_approve")
        await self._reply(
            message,
            self._s("approved", uid=user.id, name=utils.escape_html(get_display_name(user))),
        )

    @loader.command(
        ru_doc="<реплай/id/@> — убрать из памяти и разбанить (для теста)", alias="dpmunwl"
    )
    async def dpmforgetcmd(self, message: Message):
        """<reply/id/@user> — remove from memory and unblock (for re-testing)"""
        user = await self._resolve_user(message)
        if user is None:
            await self._reply(message, self._s("user_not_specified"))
            return

        self._set_whitelist([u for u in self._whitelist if u != user.id])
        self._set_banned([b for b in self._banned if b != user.id])
        with contextlib.suppress(Exception):
            await self._client(UnblockRequest(id=user.id))

        await self._reply(
            message,
            self._s("forgotten", uid=user.id, name=utils.escape_html(get_display_name(user))),
        )

    @loader.command(ru_doc="очистить всю память (вайтлист)", alias="dpmclear")
    async def dpmresetcmd(self, message: Message):
        """clear the whole whitelist memory"""
        count = len(self._whitelist)
        self._set_whitelist([])
        await self._reply(message, self._s("reset", n=count))

    @loader.command(ru_doc="показать память (вайтлист)", alias="dpmlist")
    async def dpmwlcmd(self, message: Message):
        """show the whitelist memory"""
        wl = list(self._whitelist)
        if not wl:
            await self._reply(message, self._s("wl_empty"))
            return

        rows = "\n".join(f"• <code>{uid}</code>" for uid in wl[:100])
        if len(wl) > 100:
            rows += f"\n… и ещё {len(wl) - 100}"
        await self._reply(message, self._s("wl_list", n=len(wl), rows=rows))

    @loader.watcher()
    async def watcher(self, message: Message):
        if not isinstance(message, Message) or not isinstance(message.peer_id, PeerUser):
            return

        # исходящее в ЛС забаненному → авто-разбан и одобрение
        if getattr(message, "out", False):
            await self._maybe_unblock_on_reply(message)
            return

        # входящее: фильтрация незнакомцев
        if not self.get("state", False) or utils.get_chat_id(message) in {
            1271266957,  # @replies
            777000,  # Telegram Notifications
            self._tg_id,  # сам аккаунт
        }:
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
        notify_text = self.config["custom_message"] or self._s("banned")

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

        log_name = (
            utils.escape_html(dialog.first_name)
            if dialog is not None
            else (
                getattr(getattr(message, "sender", None), "username", None)
                or message.sender_id
            )
        )
        log_body = utils.escape_html(
            "<стикер>"
            if message.sticker
            else (
                "<фото>"
                if message.photo
                else (
                    "<видео>"
                    if message.video
                    else "<файл>" if message.document else message.raw_text[:3000]
                )
            )
        )
        with contextlib.suppress(Exception):
            await self.inline.bot.send_message(
                self._client.tg_id,
                _to_bot_emoji(
                    self._s(
                        "banned_log",
                        uid=dialog.id if dialog is not None else message.sender_id,
                        name=log_name,
                        rep=_yn(self.config["report_spam"]),
                        dele=_yn(self.config["delete_dialog"]),
                        text=log_body,
                    )
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
        self._set_banned(self._banned + [message.sender_id])
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
