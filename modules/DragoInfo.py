__version__ = (1, 0, 1)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# changelog: команда .info → .di (.info занята ядром Heroku); карточка: ID, был в сети, премиум, био, общих чатов, аватар

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoInfo — карточка пользователя по .info (реплай/@user/id).║
# ╚══════════════════════════════════════════════════════════════╝

import logging

from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    User,
    UserStatusOffline,
    UserStatusOnline,
    UserStatusRecently,
    UserStatusLastMonth,
    UserStatusLastWeek,
)

from .. import loader, utils

logger = logging.getLogger(__name__)


def _display_name(entity) -> str:
    if entity is None:
        return "Deleted Account"
    first = getattr(entity, "first_name", "") or ""
    last = getattr(entity, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if not name:
        name = (
            getattr(entity, "title", "")
            or getattr(entity, "username", "")
            or "Deleted Account"
        )
    return name


def _status_text(status) -> str:
    if isinstance(status, UserStatusOnline):
        return "🟢 в сети"
    if isinstance(status, UserStatusOffline):
        when = status.was_online
        return f"⚪️ был(а) {when:%d.%m.%Y %H:%M}" if when else "⚪️ оффлайн"
    if isinstance(status, UserStatusRecently):
        return "🟡 недавно"
    if isinstance(status, UserStatusLastWeek):
        return "🟠 на этой неделе"
    if isinstance(status, UserStatusLastMonth):
        return "🔴 в этом месяце"
    return "⚫️ давно / скрыт"


@loader.tds
class DragoInfoMod(loader.Module):
    """🚹 Карточка пользователя: ID, был в сети, премиум, био, общих чатов."""

    strings = {
        "name": "DragoInfo",
        "loading": "{emoji} <b>Собираю инфо…</b>",
        "not_user": (
            "{emoji} <b>Это не пользователь.</b>\n<b>{name}</b>\nID: <code>{id}</code>"
        ),
        "fail": "🚫 <b>Не удалось получить инфо:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🚹 Карточка пользователя: ID, был в сети, премиум, био, общих чатов.",
        "dicmd_doc": "[@user/id] или реплай — карточка пользователя",
        "loading": "{emoji} <b>Собираю инфо…</b>",
        "not_user": (
            "{emoji} <b>Это не пользователь.</b>\n<b>{name}</b>\nID: <code>{id}</code>"
        ),
        "fail": "🚫 <b>Не удалось получить инфо:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "show_avatar",
                True,
                "Прикреплять аватар пользователя к карточке.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_info",
                "<emoji document_id=5258400740497466260>🚹</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _resolve(self, message):
        reply = await message.get_reply_message()
        args = (utils.get_args_raw(message) or "").strip()
        if reply:
            sender = await reply.get_sender()
            if sender is None and getattr(reply, "sender_id", None):
                sender = await self._client.get_entity(reply.sender_id)
            return sender
        if args:
            target = args.split()[0]
            try:
                target = int(target)
            except ValueError:
                pass
            return await self._client.get_entity(target)
        return await self._client.get_me()

    def _build_card(self, user: User, about: str, common: int) -> str:
        emoji = self.config["emoji_info"]
        name = utils.escape_html(_display_name(user))
        rows = [f"{emoji} <b>{name}</b>"]
        if getattr(user, "username", None):
            rows.append(f"🔗 @{user.username}")
        rows.append(f"🆔 <code>{user.id}</code>")

        flags = []
        if getattr(user, "premium", False):
            flags.append("⭐️ Premium")
        if getattr(user, "verified", False):
            flags.append("✔️ verified")
        if getattr(user, "bot", False):
            flags.append("🤖 бот")
        if getattr(user, "scam", False):
            flags.append("⚠️ scam")
        if getattr(user, "fake", False):
            flags.append("⚠️ fake")
        if flags:
            rows.append(" · ".join(flags))

        rows.append(f"👁 {_status_text(getattr(user, 'status', None))}")
        dc = getattr(getattr(user, "photo", None), "dc_id", None)
        if dc:
            rows.append(f"🌍 DC{dc}")
        if common:
            rows.append(f"🧑‍🤝‍🧑 общих чатов: <b>{common}</b>")
        if about:
            rows.append(f"\n📝 <i>{utils.escape_html(about)}</i>")
        rows.append(f'\n<a href="tg://user?id={user.id}">открыть профиль</a>')
        return "\n".join(rows)

    @loader.command(ru_doc="[@user/id] или реплай — карточка пользователя", alias="uinfo")
    async def dicmd(self, message):
        """[@user/id] or reply — user info card"""
        emoji = self.config["emoji_info"]
        status = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            entity = await self._resolve(message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("resolve failed")
            return await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        if not isinstance(entity, User):
            return await utils.answer(
                status,
                self.strings("not_user").format(
                    emoji=emoji,
                    name=utils.escape_html(_display_name(entity)),
                    id=getattr(entity, "id", "?"),
                ),
            )

        about, common = "", 0
        try:
            full = await self._client(GetFullUserRequest(entity))
            fu = getattr(full, "full_user", None)
            if fu is not None:
                about = getattr(fu, "about", "") or ""
                common = getattr(fu, "common_chats_count", 0) or 0
        except Exception as exc:  # noqa: BLE001 — нет доступа к полному профилю
            logger.info("GetFullUser failed: %s", exc)

        card = self._build_card(entity, about, common)

        if self.config["show_avatar"]:
            try:
                avatar = await self._client.download_profile_photo(entity, file=bytes)
            except Exception:  # noqa: BLE001
                avatar = None
            if avatar:
                reply = await message.get_reply_message()
                import io

                buf = io.BytesIO(avatar)
                buf.name = "avatar.jpg"
                await self._client.send_file(
                    utils.get_chat_id(message),
                    buf,
                    caption=card,
                    reply_to=reply.id if reply else None,
                )
                try:
                    await status.delete()
                except Exception:  # noqa: BLE001
                    pass
                return

        await utils.answer(status, card)
