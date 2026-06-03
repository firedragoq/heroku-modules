__version__ = (1, 3, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: aiohttp
# changelog: инлайн-режим (use_inline) — картинка кода одним сообщением от бота

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoCarbon — красивые картинки кода (carbon-style, без ключа).║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import re

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = "https://carbonara.solopov.dev/api/cook"


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )


async def _upload_image(data: bytes) -> str | None:
    """Заливает картинку на catbox→0x0, возвращает URL (для инлайн-формы)."""
    headers = {"User-Agent": "Mozilla/5.0 (DragoCarbon)"}
    timeout = aiohttp.ClientTimeout(total=30)
    hosts = [
        ("https://catbox.moe/user/api.php", "fileToUpload", {"reqtype": "fileupload"}),
        ("https://0x0.st", "file", {}),
    ]
    for url, field, extra in hosts:
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                form = aiohttp.FormData()
                for k, v in extra.items():
                    form.add_field(k, v)
                form.add_field(field, data, filename="carbon.png")
                async with s.post(url, data=form) as r:
                    body = (await r.text()).strip()
                    if body.startswith("http"):
                        return body
        except Exception as e:  # noqa: BLE001
            logger.warning("carbon upload via %s failed: %s", url, e)
    return None

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
        "caption": "{emoji} <b>DragoCarbon</b> · <code>{theme}</code>{trunc}",
        "fail": "🚫 <b>Не удалось сделать картинку:</b> <code>{}</code>",
        "trunc": "  ·  <i>обрезано до {n} строк</i>",
    }

    strings_ru = {
        "_cls_doc": "🕹 Красивые картинки кода (carbon-style, без API-ключа).",
        "carboncmd_doc": "<код> или реплай (текст/файл) — картинка кода",
        "loading": "{emoji} <b>Готовлю картинку кода…</b>",
        "caption": "{emoji} <b>DragoCarbon</b> · <code>{theme}</code>{trunc}",
        "fail": "🚫 <b>Не удалось сделать картинку:</b> <code>{}</code>",
        "trunc": "  ·  <i>обрезано до {n} строк</i>",
        "no_code": (
            "{emoji} <b>Дай код.</b> Ответь на сообщение с кодом или с файлом "
            "(.py/.js/.txt…) командой <code>{p}carbon</code>, либо "
            "<code>{p}carbon print('hi')</code>."
        ),
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
                "max_lines",
                50,
                "Макс. строк кода на картинке (длинный код обрезается — carbon "
                "для коротких сниппетов, иначе картинка нечитабельна).",
                validator=loader.validators.Integer(minimum=5, maximum=300),
            ),
            loader.ConfigValue(
                "emoji_carbon",
                "<emoji document_id=5258502965014076491>🕹</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять картинку через инлайн-бота (одним сообщением от бота).",
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

    @staticmethod
    async def _code_from_reply(reply) -> str:
        """Берёт код из реплая: текст, либо содержимое прикреплённого тексто-файла."""
        if not reply:
            return ""
        if reply.raw_text:
            return reply.raw_text
        # прикреплённый файл — пробуем как текст
        if getattr(reply, "media", None) and getattr(reply, "file", None):
            size = getattr(reply.file, "size", 0) or 0
            if size > 300 * 1024:  # не тянем большие файлы
                return ""
            try:
                raw = await reply.download_media(bytes)
                return raw.decode("utf-8")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    @loader.command(ru_doc="<код> или реплай (текст/файл) — картинка кода", alias="cb")
    async def carboncmd(self, message):
        """<code> or reply (text/file) — render a code image"""
        code = utils.get_args_raw(message)
        if not code:
            code = await self._code_from_reply(await message.get_reply_message())
        emoji = self.config["emoji_carbon"]
        if not code or not code.strip():
            return await self._reply(
                message, self.strings("no_code").format(emoji=emoji, p=self.get_prefix())
            )

        # обрезаем слишком длинный код, чтобы картинка осталась читабельной
        trunc = ""
        max_lines = int(self.config["max_lines"])
        lines = code.splitlines()
        if len(lines) > max_lines:
            code = "\n".join(lines[:max_lines])
            trunc = self.strings("trunc").format(n=max_lines)

        await self._status(message, self.strings("loading").format(emoji=emoji))
        try:
            data = await self._cook(code)
        except Exception as exc:  # noqa: BLE001
            logger.exception("carbon failed: %s", exc)
            return await self._reply(
                message, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        caption = self.strings("caption").format(
            emoji=emoji, theme=utils.escape_html(self.config["theme"]), trunc=trunc
        )
        # инлайн-режим: картинка одним сообщением от бота
        if self._inline_on:
            url = await _upload_image(data)
            if url:
                try:
                    return await self.inline.form(
                        message=message, text=_to_bot_emoji(caption), photo=url
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inline carbon failed, fallback: %s", exc)

        img = io.BytesIO(data)
        img.name = "carbon.png"
        await utils.answer(message, caption, file=img)
