__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Загрузки
# scope: heroku_only
# requires: yt-dlp
# changelog: первый релиз — .dl ссылка → видео, .dla ссылка → аудио (YouTube/TikTok/Instagram и др., без ключей)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoDownloader — .dl <url> → видео, .dla <url> → аудио.     ║
# ║  Работает на yt-dlp: YouTube, TikTok, Instagram, X, и сотни   ║
# ║  других сайтов. Без API-ключей.                              ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import glob
import logging
import os
import re
import shutil
import tempfile

import yt_dlp

from .. import loader, utils

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")


def _pick_file(tmpdir: str) -> str:
    """Берёт самый крупный файл из временной папки (итог скачивания)."""
    files = [f for f in glob.glob(os.path.join(tmpdir, "*")) if os.path.isfile(f)]
    if not files:
        raise RuntimeError("yt-dlp ничего не скачал")
    return max(files, key=os.path.getsize)


def _download(url: str, audio: bool, tmpdir: str, max_mb: int) -> tuple:
    """Синхронное скачивание через yt-dlp. Возвращает (path, info)."""
    fmt = "bestaudio/best" if audio else "best[ext=mp4]/bestvideo+bestaudio/best"
    opts = {
        "outtmpl": os.path.join(tmpdir, "%(title).70B.%(ext)s"),
        "format": fmt,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": max_mb * 1024 * 1024,
        "nocheckcertificate": True,
        "ignoreerrors": False,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else info
    return _pick_file(tmpdir), info


@loader.tds
class DragoDownloaderMod(loader.Module):
    """📥 Скачать видео/аудио по ссылке (YouTube/TikTok/Instagram и др.)."""

    strings = {
        "name": "DragoDownloader",
        "no_url": (
            "{emoji} <b>Дай ссылку.</b> <code>{p}dl https://…</code> — видео, "
            "<code>{p}dla https://…</code> — аудио. Можно реплаем на сообщение со ссылкой."
        ),
        "loading": "{emoji} <b>Скачиваю…</b> <i>{what}</i>\n<code>{url}</code>",
        "too_big": (
            "🚫 <b>Файл больше лимита</b> ({mb} МБ). Подними <code>max_mb</code> в "
            "конфиге или скачай аудио (<code>{p}dla</code>)."
        ),
        "fail": "🚫 <b>Не скачалось:</b>\n<code>{}</code>",
        "caption": "{emoji} <b>{title}</b>{author}\n<a href=\"{url}\">источник</a>",
    }

    strings_ru = {
        "_cls_doc": "📥 Скачать видео/аудио по ссылке (YouTube/TikTok/Instagram и др.).",
        "dlcmd_doc": "<ссылка> — скачать видео",
        "dlacmd_doc": "<ссылка> — скачать аудио",
        "no_url": (
            "{emoji} <b>Дай ссылку.</b> <code>{p}dl https://…</code> — видео, "
            "<code>{p}dla https://…</code> — аудио. Можно реплаем на сообщение со ссылкой."
        ),
        "loading": "{emoji} <b>Скачиваю…</b> <i>{what}</i>\n<code>{url}</code>",
        "too_big": (
            "🚫 <b>Файл больше лимита</b> ({mb} МБ). Подними <code>max_mb</code> в "
            "конфиге или скачай аудио (<code>{p}dla</code>)."
        ),
        "fail": "🚫 <b>Не скачалось:</b>\n<code>{}</code>",
        "caption": "{emoji} <b>{title}</b>{author}\n<a href=\"{url}\">источник</a>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "max_mb",
                500,
                "Максимальный размер файла для скачивания (МБ).",
                validator=loader.validators.Integer(minimum=1, maximum=2000),
            ),
            loader.ConfigValue(
                "as_streaming",
                True,
                "Слать видео с поддержкой стриминга (просмотр без полной загрузки).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "emoji_dl",
                "<emoji document_id=5258497901247631978>📥</emoji>",
                "Эмодзи модуля. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _get_url(self, message) -> str:
        raw = (utils.get_args_raw(message) or "").strip()
        m = _URL_RE.search(raw)
        if m:
            return m.group(0)
        reply = await message.get_reply_message()
        if reply and reply.raw_text:
            m = _URL_RE.search(reply.raw_text)
            if m:
                return m.group(0)
        return ""

    async def _run(self, message, audio: bool):
        emoji = self.config["emoji_dl"]
        url = await self._get_url(message)
        if not url:
            return await utils.answer(
                message, self.strings("no_url").format(emoji=emoji, p=self.get_prefix())
            )

        what = "аудио" if audio else "видео"
        status = await utils.answer(
            message,
            self.strings("loading").format(emoji=emoji, what=what, url=utils.escape_html(url)),
        )
        max_mb = int(self.config["max_mb"])
        tmpdir = tempfile.mkdtemp(prefix="dragodl_")
        try:
            path, info = await asyncio.get_event_loop().run_in_executor(
                None, _download, url, audio, tmpdir, max_mb
            )
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > max_mb:
                return await utils.answer(
                    status,
                    self.strings("too_big").format(mb=max_mb, p=self.get_prefix()),
                )

            info = info or {}
            title = (info.get("title") or os.path.basename(path))[:120]
            uploader = info.get("uploader") or info.get("channel") or ""
            src = info.get("webpage_url") or url
            author = f"\n👤 {utils.escape_html(uploader)}" if uploader else ""
            caption = self.strings("caption").format(
                emoji=emoji, title=utils.escape_html(title), author=author,
                url=utils.escape_html(src),
            )

            reply = await message.get_reply_message()
            await self._client.send_file(
                utils.get_chat_id(message),
                path,
                caption=caption,
                reply_to=reply.id if reply else None,
                supports_streaming=bool(self.config["as_streaming"]) and not audio,
                force_document=False,
            )
            await status.delete()
        except yt_dlp.utils.DownloadError as exc:
            logger.warning("yt-dlp download error: %s", exc)
            await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)[:600]))
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("download failed")
            await utils.answer(
                status, self.strings("fail").format(utils.escape_html(str(exc)[:600]))
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @loader.command(ru_doc="<ссылка> — скачать видео", alias="dl")
    async def dlcmd(self, message):
        """<url> — download video"""
        await self._run(message, audio=False)

    @loader.command(ru_doc="<ссылка> — скачать аудио", alias="dla")
    async def dlacmd(self, message):
        """<url> — download audio"""
        await self._run(message, audio=True)
