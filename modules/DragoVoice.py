__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Утилиты
# scope: heroku_only
# requires: aiohttp
# changelog: первый релиз — TTS (текст→голос, Google) и STT (голос→текст, родная транскрипция Telegram)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoVoice — текст↔голос. TTS без ключей (Google), STT через ║
# ║  встроенную транскрипцию Telegram (нужен Premium на аккаунте).║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import io
import logging
import urllib.parse

import aiohttp
from telethon.tl.functions.messages import TranscribeAudioRequest

from .. import loader, utils

logger = logging.getLogger(__name__)

# неофициальный, но стабильный endpoint Google Translate TTS (без ключа)
TTS_URL = "https://translate.google.com/translate_tts"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_CHUNK = 200  # лимит длины q у Google TTS


def _split_text(text: str, limit: int = _CHUNK) -> list:
    """Бьёт текст на куски ≤ limit по границам слов."""
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > limit:
            if cur:
                chunks.append(cur)
            # одно слово длиннее лимита — режем жёстко
            while len(w) > limit:
                chunks.append(w[:limit])
                w = w[limit:]
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text[:limit]]


@loader.tds
class DragoVoiceMod(loader.Module):
    """🗣 Текст↔голос: TTS (без ключей) и STT (транскрипция Telegram)."""

    strings = {
        "name": "DragoVoice",
        "no_text": (
            "{emoji} <b>Дай текст.</b> <code>{p}tts привет</code> или реплай на "
            "сообщение командой <code>{p}tts</code>."
        ),
        "tts_loading": "{emoji} <b>Озвучиваю…</b>",
        "tts_fail": "🚫 <b>Не удалось озвучить:</b> <code>{}</code>",
        "no_voice": (
            "{emoji} <b>Ответь на голосовое/аудио/кружок</b> командой "
            "<code>{p}stt</code>."
        ),
        "stt_loading": "{emoji} <b>Распознаю речь…</b>",
        "stt_result": "{emoji} <b>Расшифровка:</b>\n{text}",
        "stt_empty": "{emoji} <b>Пусто</b> — Telegram не вернул текст.",
        "stt_fail": (
            "🚫 <b>Не удалось распознать.</b> Встроенная транскрипция Telegram "
            "доступна с Premium на аккаунте.\n<code>{}</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "🗣 Текст↔голос: TTS (без ключей) и STT (транскрипция Telegram).",
        "ttscmd_doc": "<текст> или реплай — озвучить текст",
        "sttcmd_doc": "реплай на голосовое — расшифровать в текст",
        "no_text": (
            "{emoji} <b>Дай текст.</b> <code>{p}tts привет</code> или реплай на "
            "сообщение командой <code>{p}tts</code>."
        ),
        "tts_loading": "{emoji} <b>Озвучиваю…</b>",
        "tts_fail": "🚫 <b>Не удалось озвучить:</b> <code>{}</code>",
        "no_voice": (
            "{emoji} <b>Ответь на голосовое/аудио/кружок</b> командой "
            "<code>{p}stt</code>."
        ),
        "stt_loading": "{emoji} <b>Распознаю речь…</b>",
        "stt_result": "{emoji} <b>Расшифровка:</b>\n{text}",
        "stt_empty": "{emoji} <b>Пусто</b> — Telegram не вернул текст.",
        "stt_fail": (
            "🚫 <b>Не удалось распознать.</b> Встроенная транскрипция Telegram "
            "доступна с Premium на аккаунте.\n<code>{}</code>"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "tts_lang",
                "ru",
                "Язык озвучки TTS (ru, en, uk, de, fr, es…).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "tts_as_voice",
                True,
                "Слать TTS как голосовое (True) или как аудио-файл (False).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_voice",
                "<emoji document_id=5258343235180339728>☎</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _tts_chunk(self, session, text: str, lang: str) -> bytes:
        params = {
            "ie": "UTF-8",
            "client": "tw-ob",
            "tl": lang,
            "q": text,
            "total": "1",
            "idx": "0",
            "textlen": str(len(text)),
        }
        url = f"{TTS_URL}?{urllib.parse.urlencode(params)}"
        async with session.get(url, headers={"User-Agent": _UA}) as r:
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}")
            return await r.read()

    @loader.command(ru_doc="<текст> или реплай — озвучить текст", alias="tts")
    async def ttscmd(self, message):
        """<text> or reply — text to speech"""
        emoji = self.config["emoji_voice"]
        text = utils.get_args_raw(message)
        if not text:
            reply = await message.get_reply_message()
            text = (reply.raw_text or "") if reply else ""
        text = (text or "").strip()
        if not text:
            return await utils.answer(
                message, self.strings("no_text").format(emoji=emoji, p=self.get_prefix())
            )

        status = await utils.answer(message, self.strings("tts_loading").format(emoji=emoji))
        lang = str(self.config["tts_lang"])
        try:
            audio = b""
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                for chunk in _split_text(text):
                    audio += await self._tts_chunk(s, chunk, lang)
            if not audio:
                raise RuntimeError("пустой ответ TTS")
        except Exception as exc:  # noqa: BLE001
            logger.exception("TTS failed")
            return await utils.answer(
                status, self.strings("tts_fail").format(utils.escape_html(str(exc)))
            )

        buf = io.BytesIO(audio)
        buf.name = "voice.mp3"
        reply = await message.get_reply_message()
        try:
            await self._client.send_file(
                utils.get_chat_id(message),
                buf,
                voice_note=bool(self.config["tts_as_voice"]),
                reply_to=reply.id if reply else None,
            )
        except Exception:  # noqa: BLE001 — некоторые клиенты не примут mp3 как voice
            buf.seek(0)
            await self._client.send_file(
                utils.get_chat_id(message), buf,
                reply_to=reply.id if reply else None,
            )
        try:
            await status.delete()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _is_voice(msg) -> bool:
        if getattr(msg, "voice", None) or getattr(msg, "video_note", None):
            return True
        doc = getattr(msg, "document", None)
        mime = getattr(doc, "mime_type", "") if doc else ""
        return mime.startswith("audio/") or mime.startswith("video/")

    @loader.command(ru_doc="реплай на голосовое — расшифровать в текст", alias="stt")
    async def sttcmd(self, message):
        """reply to a voice message — speech to text"""
        emoji = self.config["emoji_voice"]
        reply = await message.get_reply_message()
        if not reply or not self._is_voice(reply):
            return await utils.answer(
                message, self.strings("no_voice").format(emoji=emoji, p=self.get_prefix())
            )

        status = await utils.answer(message, self.strings("stt_loading").format(emoji=emoji))
        try:
            peer = await reply.get_input_chat()
            text = ""
            # транскрипция может быть «pending» — опрашиваем несколько раз
            for _ in range(10):
                res = await self._client(TranscribeAudioRequest(peer=peer, msg_id=reply.id))
                text = (getattr(res, "text", "") or "").strip()
                if text and not getattr(res, "pending", 0):
                    break
                if text:
                    break
                await asyncio.sleep(1)
        except Exception as exc:  # noqa: BLE001
            logger.exception("STT failed")
            return await utils.answer(
                status, self.strings("stt_fail").format(utils.escape_html(str(exc)))
            )

        if not text:
            return await utils.answer(status, self.strings("stt_empty").format(emoji=emoji))
        await utils.answer(
            status,
            self.strings("stt_result").format(emoji=emoji, text=utils.escape_html(text)),
        )
