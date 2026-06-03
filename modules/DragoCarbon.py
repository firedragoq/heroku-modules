__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoCarbon — красивые картинки кода (carbon-style, без ключа).║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = "https://carbonara.solopov.dev/api/cook"

# популярные темы carbon (для подсказки)
_THEMES = (
    "monokai, dracula, nord, one-dark, material, night-owl, seti, "
    "synthwave-84, vscode, solarized dark, panda-syntax, shades-of-purple"
)


@loader.tds
class DragoCarbonMod(loader.Module):
    """🕹 Красивые картинки кода (carbon-style, без API-ключа)."""

    strings = {
        "name": "DragoCarbon",
        "no_code": (
            "{emoji} <b>Дай код.</b> Ответь на сообщение с кодом командой "
            "<code>{p}carbon</code> или <code>{p}carbon print('hi')</code>."
        ),
        "loading": "{emoji} <b>Готовлю картинку кода…</b>",
        "caption": "{emoji} <b>DragoCarbon</b> · <code>{theme}</code>",
        "fail": "🚫 <b>Не удалось сделать картинку:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🕹 Красивые картинки кода (carbon-style, без API-ключа).",
        "carboncmd_doc": "<код> или реплай — картинка кода",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "theme",
                "monokai",
                f"Тема оформления. Примеры: {_THEMES}.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "background",
                "#1e1e2e",
                "Цвет фона (hex или rgba).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "language",
                "auto",
                "Язык подсветки (auto, python, javascript, bash…).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "drop_shadow",
                True,
                "Тень под окном кода.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_carbon",
                "<emoji document_id=5258502965014076491>🕹</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _cook(self, code: str) -> bytes:
        payload = {
            "code": code,
            "backgroundColor": self.config["background"],
            "theme": self.config["theme"],
            "dropShadow": bool(self.config["drop_shadow"]),
            "windowControls": True,
            "language": self.config["language"],
        }
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(API, json=payload) as r:
                if r.status >= 400:
                    raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:150]}")
                return await r.read()

    @loader.command(ru_doc="<код> или реплай — картинка кода", alias="cb")
    async def carboncmd(self, message):
        """<code> or reply — render a code image"""
        code = utils.get_args_raw(message)
        if not code:
            reply = await message.get_reply_message()
            if reply and reply.raw_text:
                code = reply.raw_text
        emoji = self.config["emoji_carbon"]
        if not code or not code.strip():
            return await utils.answer(
                message, self.strings("no_code").format(emoji=emoji, p=self.get_prefix())
            )

        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            data = await self._cook(code)
        except Exception as exc:  # noqa: BLE001
            logger.exception("carbon failed: %s", exc)
            return await utils.answer(
                msg, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        img = io.BytesIO(data)
        img.name = "carbon.png"
        await utils.answer(
            message,
            self.strings("caption").format(
                emoji=emoji, theme=utils.escape_html(self.config["theme"])
            ),
            file=img,
        )
