__version__ = (1, 2, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp
# changelog: инлайн-режим (use_inline) — ответы через инлайн-бота

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoShorten — короткие ссылки + заливка фото (без ключа).    ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import re
from urllib.parse import quote

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )

_SERVICES = {
    "isgd": "https://is.gd/create.php?format=simple&url={url}",
    "vgd": "https://v.gd/create.php?format=simple&url={url}",
    "tinyurl": "https://tinyurl.com/api-create.php?url={url}",
    "clckru": "https://clck.ru/--?url={url}",
}

# Бесплатные файлхостинги без ключа (порядок = приоритет)
_IMG_HOSTS = ["catbox", "0x0"]
_UA = "Mozilla/5.0 (DragoShorten)"


@loader.tds
class DragoShortenMod(loader.Module):
    """🔗 Короткие ссылки (is.gd / TinyURL, без ключа)."""

    strings = {
        "name": "DragoShorten",
        "no_url": (
            "🚫 <b>Дай ссылку.</b> Пример: <code>{p}short https://example.com</code> "
            "(или ответом на сообщение со ссылкой)."
        ),
        "loading": "{emoji} <b>Сокращаю…</b>",
        "result": (
            "{emoji} <b>Готово</b> <i>({svc})</i>\n\n🔗 <code>{short}</code>\n"
            "↩️ <i>{orig}</i>"
        ),
        "all_failed": (
            "🚫 <b>Все сервисы отказали.</b>\n<code>{detail}</code>\n\n"
            "💡 Часто причина — блок IP хостинга. Попробуй позже."
        ),
        "expanding": "{emoji} <b>Разворачиваю…</b>",
        "expanded": "{emoji} <b>Полная ссылка:</b>\n<code>{full}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "no_media": (
            "🚫 <b>Нужно фото/файл.</b> Ответь командой <code>{p}shortimg</code> "
            "на медиа или отправь его с подписью <code>{p}shortimg</code>."
        ),
        "uploading": "{emoji} <b>Загружаю файл…</b>",
        "img_result": (
            "{emoji} <b>Файл загружен</b> <i>({host})</i>\n\n🔗 <code>{link}</code>"
        ),
        "img_result_short": (
            "{emoji} <b>Файл загружен</b> <i>({host})</i>\n\n"
            "🔗 <code>{short}</code>\n📎 <i>{link}</i>"
        ),
        "img_failed": (
            "🚫 <b>Не удалось загрузить файл.</b>\n<code>{detail}</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "🔗 Короткие ссылки + заливка фото в ссылку (без ключа).",
        "shortcmd_doc": "<url> — сократить ссылку",
        "expandcmd_doc": "<url> — развернуть короткую ссылку",
        "shortimgcmd_doc": "ответом на фото/файл — получить прямую ссылку",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "service",
                "isgd",
                "Сервис сокращения: isgd, vgd, tinyurl, clckru.",
                validator=loader.validators.Choice(list(_SERVICES)),
            ),
            loader.ConfigValue(
                "emoji_link",
                "<emoji document_id=5350695039318114023>🔗</emoji>",
                "Эмодзи ссылки. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "image_host",
                "catbox",
                "Хостинг файлов: catbox или 0x0.",
                validator=loader.validators.Choice(_IMG_HOSTS),
            ),
            loader.ConfigValue(
                "shorten_image_link",
                False,
                "Дополнительно сокращать ссылку на загруженный файл.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять ответы через инлайн-бота (от бота, а не аккаунта).",
                validator=loader.validators.Boolean(),
            ),
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

    def _target(self, message):
        """Берёт URL из аргумента или из реплая."""
        args = utils.get_args_raw(message).strip()
        if args:
            return args.split()[0]
        return None

    async def _shorten_any(self, url: str) -> tuple[str, str]:
        """Перебирает сервисы. Возвращает (сервис, короткая_ссылка) или ('', '')."""
        order = [self.config["service"]] + [
            s for s in _SERVICES if s != self.config["service"]
        ]
        for svc in order:
            try:
                return svc, await self._try_service(svc, url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("shorten via %s failed: %s", svc, exc)
        return "", ""

    async def _upload_image(self, host: str, data: bytes, fname: str) -> str:
        """Заливает файл на хостинг, возвращает прямую ссылку или бросает исключение."""
        timeout = aiohttp.ClientTimeout(total=120)
        headers = {"User-Agent": _UA}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            form = aiohttp.FormData()
            if host == "catbox":
                form.add_field("reqtype", "fileupload")
                form.add_field("fileToUpload", data, filename=fname)
                api = "https://catbox.moe/user/api.php"
            else:  # 0x0.st
                form.add_field("file", data, filename=fname)
                api = "https://0x0.st"
            async with session.post(api, data=form) as resp:
                body = (await resp.text()).strip()
                if resp.status >= 400 or not body.startswith("http"):
                    raise RuntimeError(body[:150] or f"HTTP {resp.status}")
                return body

    async def _try_service(self, svc: str, url: str) -> str:
        """Возвращает короткую ссылку или бросает исключение с текстом ошибки сервиса."""
        api = _SERVICES[svc].format(url=quote(url, safe=""))
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api, allow_redirects=False) as resp:
                # clck.ru отдаёт ссылку телом при 200, остальные — тоже телом
                body = (await resp.text()).strip()
                loc = str(resp.headers.get("Location", "")).strip()
        short = body if body.startswith("http") else (loc if loc.startswith("http") else "")
        if not short:
            raise RuntimeError(body[:150] or f"HTTP {resp.status}")
        return short

    @loader.command(ru_doc="<url> — сократить ссылку", alias="short")
    async def shortcmd(self, message):
        """<url> — shorten a link"""
        url = self._target(message)
        if not url:
            reply = await message.get_reply_message()
            if reply and reply.raw_text:
                for tok in reply.raw_text.split():
                    if tok.startswith("http"):
                        url = tok
                        break
        if not url or not url.startswith("http"):
            return await self._reply(
                message, self.strings("no_url").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_link"]
        await self._status(message, self.strings("loading").format(emoji=emoji))

        # сначала выбранный сервис, затем остальные как фолбэк
        order = [self.config["service"]] + [s for s in _SERVICES if s != self.config["service"]]
        errors = []
        for svc in order:
            try:
                short = await self._try_service(svc, url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("shorten via %s failed: %s", svc, exc)
                errors.append(f"{svc}: {exc}")
                continue
            return await self._reply(
                message,
                self.strings("result").format(
                    emoji=emoji,
                    svc=svc,
                    short=utils.escape_html(short),
                    orig=utils.escape_html(url[:120]),
                ),
            )

        logger.warning("shorten all failed: %s", errors)
        await self._reply(
            message,
            self.strings("all_failed").format(detail=utils.escape_html("; ".join(errors)[:300])),
        )

    @loader.command(ru_doc="<url> — развернуть короткую ссылку", alias="expand")
    async def expandcmd(self, message):
        """<url> — expand a short link"""
        url = self._target(message)
        if not url or not url.startswith("http"):
            return await self._reply(
                message, self.strings("no_url").format(p=self.get_prefix())
            )
        emoji = self.config["emoji_link"]
        await self._status(message, self.strings("expanding").format(emoji=emoji))
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    full = str(resp.url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("expand failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(utils.escape_html(str(exc))))
        await self._reply(
            message, self.strings("expanded").format(emoji=emoji, full=utils.escape_html(full))
        )

    @loader.command(ru_doc="ответом на фото/файл — получить прямую ссылку", alias="simg")
    async def shortimgcmd(self, message):
        """Reply to a photo/file — get a direct link"""
        # медиа в самом сообщении (фото+команда в подписи) или в реплае
        reply = await message.get_reply_message()
        source = message if message.media else (reply if reply and reply.media else None)
        if source is None:
            return await self._reply(
                message, self.strings("no_media").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_link"]
        await self._status(message, self.strings("uploading").format(emoji=emoji))
        try:
            data = await source.download_media(bytes)
        except Exception as exc:  # noqa: BLE001
            logger.exception("download failed: %s", exc)
            return await self._reply(
                message, self.strings("img_failed").format(detail=utils.escape_html(str(exc)))
            )

        ext = ""
        if getattr(source, "file", None) and source.file.ext:
            ext = source.file.ext
        fname = f"upload{ext or '.jpg'}"

        # выбранный хостинг, затем второй как фолбэк
        order = [self.config["image_host"]] + [
            h for h in _IMG_HOSTS if h != self.config["image_host"]
        ]
        link, used_host, errors = "", "", []
        for host in order:
            try:
                link = await self._upload_image(host, data, fname)
                used_host = host
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("upload via %s failed: %s", host, exc)
                errors.append(f"{host}: {exc}")
        if not link:
            logger.warning("image upload all failed: %s", errors)
            return await self._reply(
                message,
                self.strings("img_failed").format(
                    detail=utils.escape_html("; ".join(errors)[:300])
                ),
            )

        if self.config["shorten_image_link"]:
            svc, short = await self._shorten_any(link)
            if short:
                return await self._reply(
                    message,
                    self.strings("img_result_short").format(
                        emoji=emoji,
                        host=f"{used_host} → {svc}",
                        short=utils.escape_html(short),
                        link=utils.escape_html(link),
                    ),
                )

        await self._reply(
            message,
            self.strings("img_result").format(
                emoji=emoji, host=used_host, link=utils.escape_html(link)
            ),
        )
