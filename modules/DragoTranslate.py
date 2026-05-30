__version__ = (1, 1, 1)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp
# changelog: команда .dtr (алиас .dtl); убран конфликт с core-командой .tr

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoTranslate — перевод текста/реплая (Google, без ключа).   ║
# ╚══════════════════════════════════════════════════════════════╝

import logging

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = "https://translate.googleapis.com/translate_a/single"


@loader.tds
class DragoTranslateMod(loader.Module):
    """🌐 Перевод текста и реплаев (Google Translate, без ключа)."""

    strings = {
        "name": "DragoTranslate",
        "no_text": (
            "🚫 <b>Нет текста.</b> Ответь на сообщение или: "
            "<code>{p}dtr en привет</code>"
        ),
        "loading": "🌐 <b>Перевожу…</b>",
        "fail": "🚫 <b>Ошибка перевода:</b> <code>{}</code>",
        "result": (
            "{emoji} <b>Перевод</b> <code>{src}</code> → <code>{dst}</code>\n\n"
            "{text}"
        ),
    }

    strings_ru = {
        "_cls_doc": "🌐 Перевод текста и реплаев (Google Translate, без ключа).",
        "no_text": (
            "🚫 <b>Нет текста.</b> Ответь на сообщение или: "
            "<code>{p}dtr en привет</code>"
        ),
        "loading": "🌐 <b>Перевожу…</b>",
        "fail": "🚫 <b>Ошибка перевода:</b> <code>{}</code>",
        "result": (
            "{emoji} <b>Перевод</b> <code>{src}</code> → <code>{dst}</code>\n\n"
            "{text}"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "default_lang",
                "ru",
                "Язык перевода по умолчанию (код: ru, en, de…).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_title",
                "🌐",
                "Эмодзи заголовка. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _translate(self, text: str, target: str) -> tuple[str, str]:
        params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        translated = "".join(part[0] for part in data[0] if part and part[0])
        src = data[2] if len(data) > 2 else "auto"
        return translated, src

    @loader.command(ru_doc="[язык] — перевести реплай/текст", alias="dtl")
    async def dtrcmd(self, message):
        """[lang] [text] — translate reply or text"""
        args = utils.get_args_raw(message).strip()
        reply = await message.get_reply_message()

        target = self.config["default_lang"]
        text = ""
        if reply and reply.raw_text:
            # реплай: весь аргумент (если есть) — это целевой язык
            text = reply.raw_text
            if args and len(args.split()[0]) <= 5 and args.split()[0].isalpha():
                target = args.split()[0].lower()
        elif args:
            # без реплая: первый токен может быть кодом языка
            parts = args.split(maxsplit=1)
            if len(parts) == 2 and len(parts[0]) <= 5 and parts[0].isalpha():
                target, text = parts[0].lower(), parts[1]
            else:
                text = args

        if not text.strip():
            return await utils.answer(
                message, self.strings("no_text").format(p=self.get_prefix())
            )

        msg = await utils.answer(message, self.strings("loading"))
        try:
            translated, src = await self._translate(text, target)
        except Exception as exc:  # noqa: BLE001
            logger.exception("translate failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(exc))

        await utils.answer(
            msg,
            self.strings("result").format(
                emoji=self.config["emoji_title"],
                src=utils.escape_html(src),
                dst=utils.escape_html(target),
                text=utils.escape_html(translated),
            ),
        )
