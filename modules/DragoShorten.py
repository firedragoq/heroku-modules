__version__ = (1, 0, 1)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp
# changelog: URL-кодирование параметра (фикс «database insert failed» на is.gd)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoShorten — короткие ссылки (is.gd / TinyURL, без ключа).  ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
from urllib.parse import quote

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

_SERVICES = {
    "isgd": "https://is.gd/create.php?format=simple&url={url}",
    "vgd": "https://v.gd/create.php?format=simple&url={url}",
    "tinyurl": "https://tinyurl.com/api-create.php?url={url}",
    "clckru": "https://clck.ru/--?url={url}",
}


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
            "{emoji} <b>Готово</b>\n\n🔗 <code>{short}</code>\n"
            "↩️ <i>{orig}</i>"
        ),
        "expanding": "{emoji} <b>Разворачиваю…</b>",
        "expanded": "{emoji} <b>Полная ссылка:</b>\n<code>{full}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🔗 Короткие ссылки (is.gd / TinyURL, без ключа).",
        "shortcmd_doc": "<url> — сократить ссылку",
        "expandcmd_doc": "<url> — развернуть короткую ссылку",
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
        )

    def _target(self, message):
        """Берёт URL из аргумента или из реплая."""
        args = utils.get_args_raw(message).strip()
        if args:
            return args.split()[0]
        return None

    async def _get(self, url: str) -> tuple[int, str, str]:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as resp:
                body = (await resp.text()).strip()
                return resp.status, body, str(resp.headers.get("Location", ""))

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
            return await utils.answer(
                message, self.strings("no_url").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_link"]
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        api = _SERVICES[self.config["service"]].format(url=quote(url, safe=""))
        try:
            status, body, _ = await self._get(api)
            if status >= 400 or not body.startswith("http"):
                raise RuntimeError(body[:200] or f"HTTP {status}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("shorten failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(utils.escape_html(str(exc))))

        await utils.answer(
            msg,
            self.strings("result").format(
                emoji=emoji,
                short=utils.escape_html(body),
                orig=utils.escape_html(url[:120]),
            ),
        )

    @loader.command(ru_doc="<url> — развернуть короткую ссылку", alias="expand")
    async def expandcmd(self, message):
        """<url> — expand a short link"""
        url = self._target(message)
        if not url or not url.startswith("http"):
            return await utils.answer(
                message, self.strings("no_url").format(p=self.get_prefix())
            )
        emoji = self.config["emoji_link"]
        msg = await utils.answer(message, self.strings("expanding").format(emoji=emoji))
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    full = str(resp.url)
        except Exception as exc:  # noqa: BLE001
            logger.exception("expand failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(utils.escape_html(str(exc))))
        await utils.answer(
            msg, self.strings("expanded").format(emoji=emoji, full=utils.escape_html(full))
        )
