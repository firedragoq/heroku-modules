__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoScreenshot — скриншот сайта (thum.io / mshots, без ключа).║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
from urllib.parse import quote

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class DragoScreenshotMod(loader.Module):
    """📸 Скриншот веб-страницы (thum.io / mshots, без ключа)."""

    strings = {
        "name": "DragoScreenshot",
        "no_url": (
            "🚫 <b>Дай ссылку.</b> Пример: <code>{p}shot https://example.com</code> "
            "(или ответом на сообщение со ссылкой)."
        ),
        "loading": "{emoji} <b>Делаю скриншот…</b>",
        "caption": "{emoji} <b>Скриншот</b>\n🔗 <i>{url}</i>",
        "fail": "🚫 <b>Не удалось сделать скриншот:</b> <code>{}</code>",
        "too_small": (
            "🚫 <b>Сервис вернул пустую/слишком маленькую картинку.</b> "
            "Попробуй другой <code>provider</code> в конфиге или повтори позже."
        ),
    }

    strings_ru = {
        "_cls_doc": "📸 Скриншот веб-страницы (thum.io / mshots, без ключа).",
        "shotcmd_doc": "<url> — сделать скриншот сайта",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "provider",
                "thumio",
                "Сервис скриншота: thumio или mshots.",
                validator=loader.validators.Choice(["thumio", "mshots"]),
            ),
            loader.ConfigValue(
                "width",
                1280,
                "Ширина скриншота (px).",
                validator=loader.validators.Integer(minimum=320, maximum=2560),
            ),
            loader.ConfigValue(
                "fullpage",
                False,
                "thum.io: снимать всю страницу целиком (иначе — первый экран).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "as_file",
                False,
                "Отправлять как файл-документ (а не фото).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_shot",
                "📸",
                "Эмодзи скриншота. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    def _build_url(self, url: str) -> str:
        width = int(self.config["width"])
        if self.config["provider"] == "mshots":
            return f"https://s.wordpress.com/mshots/v1/{quote(url, safe='')}?w={width}"
        # thum.io
        parts = ["https://image.thum.io/get", f"width/{width}"]
        if not self.config["fullpage"]:
            parts.append(f"crop/{int(width * 0.62)}")
        parts.append("noanimate")
        parts.append(url)
        return "/".join(parts)

    async def _fetch(self, url: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=45)
        headers = {"User-Agent": "Mozilla/5.0 (DragoScreenshot)"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()

    @loader.command(ru_doc="<url> — скриншот сайта", alias="ss")
    async def shotcmd(self, message):
        """<url> — screenshot a website"""
        url = utils.get_args_raw(message).strip()
        if not url:
            reply = await message.get_reply_message()
            if reply and reply.raw_text:
                for tok in reply.raw_text.split():
                    if tok.startswith("http"):
                        url = tok
                        break
        if url and not url.startswith("http"):
            url = "https://" + url
        if not url:
            return await utils.answer(
                message, self.strings("no_url").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_shot"]
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            data = await self._fetch(self._build_url(url))
        except Exception as exc:  # noqa: BLE001
            logger.exception("screenshot failed: %s", exc)
            return await utils.answer(
                msg, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        if len(data) < 2048:
            return await utils.answer(msg, self.strings("too_small"))

        img = io.BytesIO(data)
        img.name = "screenshot.png"
        caption = self.strings("caption").format(
            emoji=emoji, url=utils.escape_html(url[:120])
        )
        await utils.answer(
            message,
            caption,
            file=img,
            force_document=bool(self.config["as_file"]),
        )
