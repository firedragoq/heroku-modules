__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: aiohttp
# changelog: первый релиз — распознавание текста с картинки (OCR.space), выбор языка и движка

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoOCR — распознать текст с картинки (реплай на фото).     ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = "https://api.ocr.space/parse/image"

# поддерживаемые языки OCR.space (движок 1) — для подсказки
_LANGS = (
    "rus, eng, ukr, ger, fre, spa, ita, pol, por, tur, "
    "ara, chs (кит.упр), jpn, kor"
)

# OCR.space free: файл до ~1 МБ
_MAX_BYTES = 1024 * 1024


@loader.tds
class DragoOCRMod(loader.Module):
    """🧐 Распознать текст с картинки (реплай на фото → текст)."""

    strings = {
        "name": "DragoOCR",
        "no_image": (
            "{emoji} <b>Ответь на картинку</b> командой <code>{p}ocr</code> "
            "(фото или картинка-файл)."
        ),
        "too_big": (
            "{emoji} <b>Картинка больше 1 МБ</b> — бесплатный OCR такие не берёт. "
            "Сожми изображение и попробуй снова."
        ),
        "loading": "{emoji} <b>Распознаю текст…</b>",
        "empty": "{emoji} <b>Текст не найден.</b> Попробуй другой язык/движок в конфиге.",
        "result": "{emoji} <b>Распознанный текст</b> (<code>{lang}</code>):\n\n{text}",
        "fail": "🚫 <b>Не удалось распознать:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🧐 Распознать текст с картинки (реплай на фото → текст).",
        "ocrcmd_doc": "реплай на картинку — распознать текст",
        "no_image": (
            "{emoji} <b>Ответь на картинку</b> командой <code>{p}ocr</code> "
            "(фото или картинка-файл)."
        ),
        "too_big": (
            "{emoji} <b>Картинка больше 1 МБ</b> — бесплатный OCR такие не берёт. "
            "Сожми изображение и попробуй снова."
        ),
        "loading": "{emoji} <b>Распознаю текст…</b>",
        "empty": "{emoji} <b>Текст не найден.</b> Попробуй другой язык/движок в конфиге.",
        "result": "{emoji} <b>Распознанный текст</b> (<code>{lang}</code>):\n\n{text}",
        "fail": "🚫 <b>Не удалось распознать:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "api_key",
                "helloworld",
                "Ключ OCR.space. 'helloworld' — демо (лимит). Бесплатный свой: "
                "ocr.space/ocrapi (выше лимиты и точность).",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "language",
                "rus",
                f"Язык текста на картинке. Варианты: {_LANGS}.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "ocr_engine",
                2,
                "Движок OCR.space: 1 — стабилен для кириллицы (нужен точный язык), "
                "2 — авто-детект и лучше для латиницы.",
                validator=loader.validators.Integer(minimum=1, maximum=2),
            ),
            loader.ConfigValue(
                "emoji_ocr",
                "<emoji document_id=5258398773402443128>🧐</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    @staticmethod
    def _is_image(msg) -> bool:
        if getattr(msg, "photo", None):
            return True
        doc = getattr(msg, "document", None)
        if doc and getattr(doc, "mime_type", "").startswith("image/"):
            return True
        return bool(getattr(msg, "sticker", None))

    async def _recognize(self, data: bytes, filename: str) -> str:
        form = aiohttp.FormData()
        form.add_field("apikey", str(self.config["api_key"]))
        form.add_field("language", str(self.config["language"]))
        form.add_field("OCREngine", str(self.config["ocr_engine"]))
        form.add_field("scale", "true")
        form.add_field("detectOrientation", "true")
        form.add_field("isOverlayRequired", "false")
        form.add_field("file", data, filename=filename, content_type="application/octet-stream")

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(API, data=form) as r:
                if r.status >= 400:
                    raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:150]}")
                payload = await r.json(content_type=None)

        if payload.get("IsErroredOnProcessing"):
            err = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR error"
            if isinstance(err, list):
                err = "; ".join(err)
            raise RuntimeError(str(err)[:200])

        results = payload.get("ParsedResults") or []
        text = "\n".join((res.get("ParsedText") or "").strip() for res in results)
        return text.strip()

    @loader.command(ru_doc="реплай на картинку — распознать текст", alias="ocr")
    async def ocrcmd(self, message):
        """reply to an image — recognize text"""
        emoji = self.config["emoji_ocr"]
        reply = await message.get_reply_message()
        if not reply or not self._is_image(reply):
            return await utils.answer(
                message,
                self.strings("no_image").format(emoji=emoji, p=self.get_prefix()),
            )

        size = getattr(getattr(reply, "file", None), "size", 0) or 0
        if size and size > _MAX_BYTES:
            return await utils.answer(message, self.strings("too_big").format(emoji=emoji))

        status = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            data = await reply.download_media(bytes)
            if not data:
                raise RuntimeError("не удалось скачать картинку")
            if len(data) > _MAX_BYTES:
                return await utils.answer(status, self.strings("too_big").format(emoji=emoji))
            text = await self._recognize(data, "image.png")
        except Exception as exc:  # noqa: BLE001
            logger.exception("DragoOCR failed")
            return await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        if not text:
            return await utils.answer(status, self.strings("empty").format(emoji=emoji))

        lang = utils.escape_html(str(self.config["language"]))
        # длинный текст — отдельным .txt-файлом, чтобы не упереться в лимит 4096
        if len(text) > 3500:
            buf = io.BytesIO(text.encode("utf-8"))
            buf.name = "ocr.txt"
            await utils.answer(
                message,
                self.strings("result").format(
                    emoji=emoji, lang=lang, text="<i>см. файл ниже</i>"
                ),
                file=buf,
            )
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
            return

        await utils.answer(
            status,
            self.strings("result").format(
                emoji=emoji, lang=lang, text=utils.escape_html(text)
            ),
        )
