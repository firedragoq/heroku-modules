__version__ = (1, 0, 2)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp
# changelog: авто-перебор сервисов при ошибке (is.gd блокирует IP некоторых хостов)

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
            return await utils.answer(
                message, self.strings("no_url").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_link"]
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))

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
            return await utils.answer(
                msg,
                self.strings("result").format(
                    emoji=emoji,
                    svc=svc,
                    short=utils.escape_html(short),
                    orig=utils.escape_html(url[:120]),
                ),
            )

        logger.warning("shorten all failed: %s", errors)
        await utils.answer(
            msg,
            self.strings("all_failed").format(detail=utils.escape_html("; ".join(errors)[:300])),
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
