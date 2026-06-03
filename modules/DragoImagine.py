__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: ИИ и текст
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoImagine — генерация картинок по тексту (Pollinations).   ║
# ║  Без API-ключа.                                                ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import random
import re
from urllib.parse import quote

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = (
    "https://image.pollinations.ai/prompt/{prompt}"
    "?width={w}&height={h}&seed={seed}&model={model}&nologo=true"
)


def _to_bot_emoji(text: str) -> str:
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )


@loader.tds
class DragoImagineMod(loader.Module):
    """🎨 Генерация картинок по тексту (Pollinations, без ключа)."""

    strings = {
        "name": "DragoImagine",
        "no_prompt": (
            "{emoji} <b>Опиши картинку.</b> Пример: "
            "<code>{p}img кот-космонавт в неоне</code>."
        ),
        "drawing": "{emoji} <b>Рисую…</b> <i>{prompt}</i>",
        "caption": "{emoji} <b>{prompt}</b>\n<i>{model} · {w}×{h}</i>",
        "fail": "🚫 <b>Не удалось сгенерировать:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🎨 Генерация картинок по тексту (Pollinations, без ключа).",
        "imgcmd_doc": "<описание> — сгенерировать картинку",
        "no_prompt": (
            "{emoji} <b>Опиши картинку.</b> Пример: "
            "<code>{p}img кот-космонавт в неоне</code>."
        ),
        "drawing": "{emoji} <b>Рисую…</b> <i>{prompt}</i>",
        "caption": "{emoji} <b>{prompt}</b>\n<i>{model} · {w}×{h}</i>",
        "fail": "🚫 <b>Не удалось сгенерировать:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "model",
                "flux",
                "Модель: flux, flux-realism, flux-anime, flux-3d, turbo.",
                validator=loader.validators.Choice(
                    ["flux", "flux-realism", "flux-anime", "flux-3d", "turbo"]
                ),
            ),
            loader.ConfigValue(
                "width",
                1024,
                "Ширина картинки (px).",
                validator=loader.validators.Integer(minimum=256, maximum=2048),
            ),
            loader.ConfigValue(
                "height",
                1024,
                "Высота картинки (px).",
                validator=loader.validators.Integer(minimum=256, maximum=2048),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять картинку через инлайн-бота (одним сообщением от бота).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_art",
                "🎨",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    def _build_url(self, prompt: str) -> tuple[str, int]:
        seed = random.randint(1, 10_000_000)
        url = API.format(
            prompt=quote(prompt, safe=""),
            w=int(self.config["width"]),
            h=int(self.config["height"]),
            seed=seed,
            model=self.config["model"],
        )
        return url, seed

    @loader.command(ru_doc="<описание> — сгенерировать картинку", alias="imagine")
    async def imgcmd(self, message):
        """<prompt> — generate an image"""
        prompt = utils.get_args_raw(message).strip()
        if not prompt:
            reply = await message.get_reply_message()
            if reply and reply.raw_text:
                prompt = reply.raw_text.strip()
        emoji = self.config["emoji_art"]
        if not prompt:
            return await utils.answer(
                message, self.strings("no_prompt").format(emoji=emoji, p=self.get_prefix())
            )

        url, _ = self._build_url(prompt)
        w, h = int(self.config["width"]), int(self.config["height"])
        caption = self.strings("caption").format(
            emoji=emoji, prompt=utils.escape_html(prompt[:200]),
            model=self.config["model"], w=w, h=h,
        )

        # инлайн-режим: картинка по URL одним сообщением от бота
        if self.config["use_inline"] and getattr(self, "inline", None):
            try:
                return await self.inline.form(
                    message=message, text=_to_bot_emoji(caption), photo=url
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("inline img failed, fallback: %s", exc)

        msg = await utils.answer(
            message,
            self.strings("drawing").format(emoji=emoji, prompt=utils.escape_html(prompt[:120])),
        )
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(url) as r:
                    r.raise_for_status()
                    data = await r.read()
            if len(data) < 1024:
                raise RuntimeError("пустой ответ сервиса")
        except Exception as exc:  # noqa: BLE001
            logger.exception("imagine failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(utils.escape_html(str(exc))))

        img = io.BytesIO(data)
        img.name = "dragoimagine.png"
        await utils.answer(message=message, response=caption, file=img)
