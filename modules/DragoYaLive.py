__version__ = (2, 4, 0)
# changelog: ретрай с backoff при таймауте Ynison (тихий повтор, warning вместо спама error)

# meta developer: @dragomodules
# meta pic: https://raw.githubusercontent.com/firedragoq/heroku-modules/main/modules/DragoYaLive.py
# scope: heroku_only
# requires: yandex-music aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoYaLive — постит играющий трек Яндекс.Музыки в канал.     ║
# ║  Текст полностью настраивается в конфиге (HTML + emoji).       ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import io
import json
import logging
import random
import string
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from yandex_music import ClientAsync

from .. import loader, utils

logger = logging.getLogger(__name__)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


async def get_current_track(client, token, retries: int = 2):
    """Получает текущий трек с ретраями. Таймауты/обрывы — тихий повтор с backoff,
    в лог уходит warning (а не error), чтобы не спамить при сетевых сбоях Ynison."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await _get_current_track_once(client, token)
        except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))  # backoff 1.5s, 3s
                continue
        except Exception as e:  # noqa: BLE001 — прочие ошибки не ретраим
            logger.error(f"Failed to get current track: {e}")
            return {"success": False}
    logger.warning(f"Ynison недоступен после {retries + 1} попыток: {last_exc}")
    return {"success": False}


async def _get_current_track_once(client, token):
    """Одна попытка получить трек. Исключения пробрасываются наверх для ретрая."""
    device_info = {"app_name": "Chrome", "type": 1}
    ws_proto = {
        "Ynison-Device-Id": "".join(
            [random.choice(string.ascii_lowercase) for _ in range(16)]
        ),
        "Ynison-Device-Info": json.dumps(device_info),
    }
    timeout = aiohttp.ClientTimeout(total=15, connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(
            url="wss://ynison.music.yandex.ru/redirector.YnisonRedirectService/GetRedirectToYnison",
            headers={
                "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(ws_proto)}",
                "Origin": "http://music.yandex.ru",
                "Authorization": f"OAuth {token}",
            },
            timeout=10,
        ) as ws:
            recv = await ws.receive()
            data = json.loads(recv.data)

        if "redirect_ticket" not in data or "host" not in data:
            return {"success": False}

        new_ws_proto = ws_proto.copy()
        new_ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

        to_send = {
            "update_full_state": {
                "player_state": {
                    "player_queue": {
                        "current_playable_index": -1,
                        "entity_id": "",
                        "entity_type": "VARIOUS",
                        "playable_list": [],
                        "options": {"repeat_mode": "NONE"},
                        "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                        "version": {
                            "device_id": ws_proto["Ynison-Device-Id"],
                            "version": 9021243204784341000,
                            "timestamp_ms": 0,
                        },
                        "from_optional": "",
                    },
                    "status": {
                        "duration_ms": 0,
                        "paused": True,
                        "playback_speed": 1,
                        "progress_ms": 0,
                        "version": {
                            "device_id": ws_proto["Ynison-Device-Id"],
                            "version": 8321822175199937000,
                            "timestamp_ms": 0,
                        },
                    },
                },
                "device": {
                    "capabilities": {
                        "can_be_player": True,
                        "can_be_remote_controller": False,
                        "volume_granularity": 16,
                    },
                    "info": {
                        "device_id": ws_proto["Ynison-Device-Id"],
                        "type": "WEB",
                        "title": "Chrome Browser",
                        "app_name": "Chrome",
                    },
                    "volume_info": {"volume": 0},
                    "is_shadow": True,
                },
                "is_currently_active": False,
            },
            "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
            "player_action_timestamp_ms": 0,
            "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
        }

        async with session.ws_connect(
            url=f"wss://{data['host']}/ynison_state.YnisonStateService/PutYnisonState",
            headers={
                "Sec-WebSocket-Protocol": f"Bearer, v2, {json.dumps(new_ws_proto)}",
                "Origin": "http://music.yandex.ru",
                "Authorization": f"OAuth {token}",
            },
            timeout=10,
            method="GET",
        ) as ws:
            await ws.send_str(json.dumps(to_send))
            recv = await asyncio.wait_for(ws.receive(), timeout=10)
            ynison = json.loads(recv.data)
            track_index = ynison["player_state"]["player_queue"][
                "current_playable_index"
            ]
            if track_index == -1:
                return {"success": False}

            track = ynison["player_state"]["player_queue"]["playable_list"][
                track_index
            ]

        await session.close()
        track_full_info = await client.tracks(track["playable_id"])

        return {
            "paused": ynison["player_state"]["status"]["paused"],
            "duration_ms": ynison["player_state"]["status"]["duration_ms"],
            "progress_ms": ynison["player_state"]["status"]["progress_ms"],
            "entity_id": ynison["player_state"]["player_queue"]["entity_id"],
            "repeat_mode": ynison["player_state"]["player_queue"]["options"][
                "repeat_mode"
            ],
            "entity_type": ynison["player_state"]["player_queue"]["entity_type"],
            "track": track_full_info,
            "success": True,
        }


def _to_int(v) -> int:
    """Безопасное приведение к int (Ynison может слать числа строками)."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _fmt_ms(ms) -> str:
    """Миллисекунды → 'м:сс'."""
    s = _to_int(ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _progress_bar(progress_ms, duration_ms, width: int = 12) -> str:
    """Текстовый прогресс-бар воспроизведения."""
    dur = _to_int(duration_ms)
    if not dur:
        return ""
    filled = max(0, min(width, round(width * _to_int(progress_ms) / dur)))
    return "▬" * filled + "🔘" + "▬" * (width - filled)


# Текст по умолчанию. Поддерживает HTML-форматирование и премиум-эмодзи
# (emoji-тег с числовым document_id). Доступные плейсхолдеры:
# {title} {artists} {album} {url} {cover} {track_id} {timestamp}
# {duration} {progress} {bar}
DEFAULT_TEXT = (
    "<emoji document_id=5474304919651491706>🎧</emoji> <b>Сейчас играет</b>\n\n"
    "<emoji document_id=5242574232688298747>🎵</emoji> <b>{title}</b>\n"
    "<emoji document_id=6039404727542747508>🎤</emoji> {artists}\n"
    "{bar} <code>{progress} / {duration}</code>\n\n"
    '<emoji document_id=6039630677182254664>🔗</emoji> '
    '<a href="{url}">Слушать на Яндекс Музыке</a>'
)


@loader.tds
class DragoYaLiveMod(loader.Module):
    """🎧 Постит играющий трек Яндекс.Музыки в канал (текст настраивается)."""

    strings = {
        "name": "DragoYaLive",
        "no_token": "🚫 <b>Не задан</b> <code>YandexMusicToken</code> <b>в конфиге.</b>",
        "no_channel": "🚫 <b>Не задан</b> <code>channel_id</code> <b>в конфиге.</b>",
        "auth_fail": "🚫 <b>Ошибка авторизации в Яндекс.Музыке. Проверь токен.</b>",
        "auth_ok": "✅ <b>Авторизация в Яндекс.Музыке успешна.</b>",
        "enabled": "✅ <b>DragoYaLive включён</b> — треки будут постаться в канал.",
        "disabled": "💤 <b>DragoYaLive выключен.</b>",
        "preview": "👁 <b>Превью поста:</b>",
        "nothing": "🔇 <b>Сейчас ничего не играет.</b>",
    }

    strings_ru = {
        "_cls_doc": "🎧 Постит играющий трек Яндекс.Музыки в канал (текст настраивается).",
        "no_token": "🚫 <b>Не задан</b> <code>YandexMusicToken</code> <b>в конфиге.</b>",
        "no_channel": "🚫 <b>Не задан</b> <code>channel_id</code> <b>в конфиге.</b>",
        "auth_fail": "🚫 <b>Ошибка авторизации в Яндекс.Музыке. Проверь токен.</b>",
        "auth_ok": "✅ <b>Авторизация в Яндекс.Музыке успешна.</b>",
        "enabled": "✅ <b>DragoYaLive включён</b> — треки будут постаться в канал.",
        "disabled": "💤 <b>DragoYaLive выключен.</b>",
        "preview": "👁 <b>Превью поста:</b>",
        "nothing": "🔇 <b>Сейчас ничего не играет.</b>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "YandexMusicToken",
                None,
                "Токен Яндекс Музыки. https://yandex-music.readthedocs.io/en/main/token.html",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "channel_id",
                None,
                "ID канала для публикации треков (например -1001234567890).",
            ),
            loader.ConfigValue(
                "check_interval",
                30,
                "Интервал проверки нового трека, сек (5–300).",
                validator=loader.validators.Integer(minimum=5, maximum=300),
            ),
            loader.ConfigValue(
                "message_text",
                DEFAULT_TEXT,
                "Текст поста. Поддерживает HTML и премиум-эмодзи. "
                "Плейсхолдеры: {title} {artists} {url} {track_id} {timestamp}",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "send_silent",
                False,
                "Постить без звука (тихие уведомления).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "send_cover",
                True,
                "Прикреплять обложку трека картинкой к посту.",
                validator=loader.validators.Boolean(),
            ),
        )
        self.last_track_id = None
        self.client_ym = None

    async def init(self):
        self.autochannel_loop.interval = self.config["check_interval"]

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.autochannel_loop.interval = self.config["check_interval"]
        await self._init_ym()

    async def _init_ym(self) -> bool:
        token = self.config["YandexMusicToken"]
        if not token:
            logger.error("YandexMusicToken не установлен")
            return False
        try:
            self.client_ym = ClientAsync(token)
            await self.client_ym.init()
            status = await self.client_ym.account_status()
            return bool(status)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка инициализации Яндекс.Музыки: {e}")
            self.client_ym = None
            return False

    async def _get_track(self):
        if not self.client_ym and not await self._init_ym():
            return None
        try:
            respond = await get_current_track(
                self.client_ym, self.config["YandexMusicToken"]
            )
            if not respond.get("success") or not respond.get("track"):
                return None

            track_obj = respond["track"][0]
            title = getattr(track_obj, "title", "Неизвестный трек")
            artists = getattr(track_obj, "artists", [])
            albums = getattr(track_obj, "albums", [])
            album_id = (
                albums[0].id if albums and getattr(albums[0], "id", None) else 0
            )
            album_name = albums[0].title if albums and getattr(albums[0], "title", None) else ""
            # обложка трека (cover_uri вида "avatars.../%%")
            cover_uri = getattr(track_obj, "cover_uri", None)
            cover = (
                "https://" + cover_uri.replace("%%", "400x400") if cover_uri else ""
            )
            url = f"https://music.yandex.ru/album/{album_id}/track/{track_obj.id}"
            # длительность трека и текущая позиция воспроизведения
            duration_ms = _to_int(getattr(track_obj, "duration_ms", 0)) or _to_int(
                respond.get("duration_ms", 0)
            )
            progress_ms = _to_int(respond.get("progress_ms", 0))
            return {
                "title": title,
                "artists": [a.name for a in artists],
                "album": album_name,
                "cover": cover,
                "url": url,
                "track_id": track_obj.id,
                "duration_ms": duration_ms,
                "progress_ms": progress_ms,
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка получения трека: {e}")
            self.client_ym = None
            return None

    def _render(self, track) -> str:
        """Подставляет данные трека в шаблон из конфига (безопасно к {})."""
        timestamp = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M:%S МСК")
        dur = track.get("duration_ms", 0)
        prog = track.get("progress_ms", 0)
        repls = {
            "{title}": utils.escape_html(track["title"]),
            "{artists}": utils.escape_html(", ".join(track["artists"])),
            "{album}": utils.escape_html(track.get("album", "")),
            "{url}": track["url"],
            "{cover}": track.get("cover", ""),
            "{track_id}": str(track["track_id"]),
            "{timestamp}": timestamp,
            "{duration}": _fmt_ms(dur),
            "{progress}": _fmt_ms(prog),
            "{bar}": _progress_bar(prog, dur),
        }
        out = self.config["message_text"] or DEFAULT_TEXT
        for key, value in repls.items():
            out = out.replace(key, value)
        return out

    async def _post(self, chat_id: int, track: dict, text: str):
        """Постит трек: с обложкой (если включено и текст влезает) или текстом."""
        cover = track.get("cover", "")
        silent = bool(self.config["send_silent"])
        if self.config["send_cover"] and cover and len(text) <= 1024:
            try:
                # скачиваем обложку в память с именем .jpg, иначе Telegram
                # отправит URL без расширения как файл, а не как фото
                async with aiohttp.ClientSession() as session:
                    async with session.get(cover) as resp:
                        resp.raise_for_status()
                        data = await resp.read()
                img = io.BytesIO(data)
                img.name = "cover.jpg"
                await self.client.send_file(
                    chat_id,
                    img,
                    caption=text,
                    parse_mode="html",
                    silent=silent,
                    force_document=False,
                )
                return
            except Exception as e:  # noqa: BLE001
                logger.error(f"Не удалось отправить с обложкой: {e}")
        await self.client.send_message(
            chat_id, text, parse_mode="html", silent=silent
        )

    @loader.loop(interval=30, autostart=True)
    async def autochannel_loop(self):
        if self.autochannel_loop.interval != self.config["check_interval"]:
            self.autochannel_loop.interval = self.config["check_interval"]
        if not self.get("autochannel", False):
            return
        if not self.config["channel_id"] or not self.config["YandexMusicToken"]:
            return
        try:
            track = await self._get_track()
            if not track:
                return
            if track["track_id"] == self.last_track_id:
                return
            self.last_track_id = track["track_id"]
            await self._post(
                int(self.config["channel_id"]), track, self._render(track)
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка в autochannel_loop: {e}")

    @loader.command(ru_doc="🎧 Вкл/выкл постинг треков в канал", alias="yalive")
    async def dyalivecmd(self, message):
        """🎧 Toggle posting tracks to the channel"""
        state = not self.get("autochannel", False)
        if state:
            if not self.config["YandexMusicToken"]:
                return await utils.answer(message, self.strings("no_token"))
            if not self.config["channel_id"]:
                return await utils.answer(message, self.strings("no_channel"))
            if not await self._init_ym():
                return await utils.answer(message, self.strings("auth_fail"))
        self.set("autochannel", state)
        await utils.answer(
            message, self.strings("enabled" if state else "disabled")
        )

    @loader.command(ru_doc="🔎 Проверить авторизацию в Яндекс.Музыке")
    async def dyacheckcmd(self, message):
        """🔎 Check Yandex.Music authorization"""
        ok = await self._init_ym()
        await utils.answer(message, self.strings("auth_ok" if ok else "auth_fail"))

    @loader.command(ru_doc="👁 Показать превью поста по текущему треку")
    async def dyapreviewcmd(self, message):
        """👁 Preview the post for the current track"""
        if not await self._init_ym():
            return await utils.answer(message, self.strings("auth_fail"))
        track = await self._get_track()
        if not track:
            return await utils.answer(message, self.strings("nothing"))
        # Само превью шлём от аккаунта (premium) — так рендерятся премиум-эмодзи,
        # ровно как будет выглядеть пост в канале.
        await self.client.send_message(
            message.peer_id,
            self.strings("preview") + "\n\n" + self._render(track),
            parse_mode="html",
        )
        # Кнопку публикации даёт инлайн-бот отдельным сообщением.
        await self.inline.form(
            message=message,
            text="📤 <b>Опубликовать этот трек в канал?</b>",
            reply_markup=[
                {
                    "text": "📢 Опубликовать сейчас",
                    "callback": self._publish_now,
                    "args": (track,),
                },
                {"text": "❌ Закрыть", "action": "close"},
            ],
        )

    async def _publish_now(self, call, track):
        """Колбэк кнопки — публикует трек в канал немедленно."""
        if not self.config["channel_id"]:
            return await call.edit(self.strings("no_channel"))
        try:
            self.last_track_id = track["track_id"]
            await self._post(
                int(self.config["channel_id"]), track, self._render(track)
            )
            await call.edit("✅ <b>Опубликовано в канал!</b>")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка ручной публикации: {e}")
            await call.edit(f"🚫 <b>Ошибка публикации:</b> <code>{e}</code>")
