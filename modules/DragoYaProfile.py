__version__ = (1, 0, 1)
# changelog: пауза больше не считается «ничего не играет» (трек ставится и на паузе); снятие при паузе вынесено в опцию clear_on_pause

# meta developer: @dragomodules
# meta pic: https://raw.githubusercontent.com/firedragoq/heroku-modules/main/modules/DragoYaProfile.py
# scope: heroku_only
# requires: yandex-music aiohttp

# ╔══════════════════════════════════════════════════════════════════╗
# ║  DragoYaProfile — ставит играющий трек Яндекс.Музыки в профиль.    ║
# ║  Слушает, что играет, и обновляет «музыку в профиле» Telegram      ║
# ║  (account.saveMusic). Требуется Telegram Premium.                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import asyncio
import io
import json
import logging
import random
import string

import aiohttp
import telethon
from telethon.tl.types import DocumentAttributeAudio, InputDocument
from yandex_music import ClientAsync

from .. import loader, utils

# account.saveMusic появился в свежих слоях API — на старом hikkatl его может
# не быть, поэтому импорт мягкий (модуль всё равно загрузится и подскажет).
try:
    from telethon.tl.functions.account import SaveMusicRequest

    _HAS_SAVE_MUSIC = True
except ImportError:  # pragma: no cover
    SaveMusicRequest = None
    _HAS_SAVE_MUSIC = False

logger = logging.getLogger(__name__)


async def get_current_track(client, token, retries: int = 2):
    """Текущий трек с ретраями. Таймауты/обрывы — тихий повтор с backoff."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await _get_current_track_once(client, token)
        except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to get current track: {e}")
            return {"success": False}
    logger.warning(f"Ynison недоступен после {retries + 1} попыток: {last_exc}")
    return {"success": False}


async def _get_current_track_once(client, token):
    """Одна попытка получить играющий трек через Ynison (как в DragoYaLive)."""
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
            "track": track_full_info,
            "success": True,
        }


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


@loader.tds
class DragoYaProfileMod(loader.Module):
    """🎧 Ставит играющий трек Яндекс.Музыки в музыку профиля Telegram."""

    strings = {
        "name": "DragoYaProfile",
        "no_token": "🚫 <b>Не задан</b> <code>YandexMusicToken</code> <b>в конфиге.</b>",
        "no_api": (
            "🚫 <b>Твой hikkatl не знает про</b> <code>account.saveMusic</code><b>.</b>\n"
            "Обнови Heroku/hikkatl до свежего слоя API."
        ),
        "auth_fail": "🚫 <b>Ошибка авторизации в Яндекс.Музыке. Проверь токен.</b>",
        "auth_ok": "✅ <b>Авторизация в Яндекс.Музыке успешна.</b>",
        "enabled": "✅ <b>Синхронизация музыки профиля включена.</b>",
        "disabled": "💤 <b>Синхронизация выключена.</b>",
        "nothing": "🔇 <b>Сейчас ничего не играет.</b>",
        "set": "🎧 <b>В профиль поставлен трек:</b>\n<b>{title}</b> — {artists}",
        "cleared": "🧹 <b>Музыка профиля очищена.</b>",
        "wait": "⏳ <b>Ставлю трек в профиль…</b>",
        "premium": (
            "🚫 <b>Похоже, музыка в профиле требует Telegram Premium "
            "(или недоступна для аккаунта).</b>\n<code>{err}</code>"
        ),
    }

    strings_ru = {
        "_cls_doc": "🎧 Ставит играющий трек Яндекс.Музыки в музыку профиля Telegram.",
        "no_token": "🚫 <b>Не задан</b> <code>YandexMusicToken</code> <b>в конфиге.</b>",
        "no_api": (
            "🚫 <b>Твой hikkatl не знает про</b> <code>account.saveMusic</code><b>.</b>\n"
            "Обнови Heroku/hikkatl до свежего слоя API."
        ),
        "auth_fail": "🚫 <b>Ошибка авторизации в Яндекс.Музыке. Проверь токен.</b>",
        "auth_ok": "✅ <b>Авторизация в Яндекс.Музыке успешна.</b>",
        "enabled": "✅ <b>Синхронизация музыки профиля включена.</b>",
        "disabled": "💤 <b>Синхронизация выключена.</b>",
        "nothing": "🔇 <b>Сейчас ничего не играет.</b>",
        "set": "🎧 <b>В профиль поставлен трек:</b>\n<b>{title}</b> — {artists}",
        "cleared": "🧹 <b>Музыка профиля очищена.</b>",
        "wait": "⏳ <b>Ставлю трек в профиль…</b>",
        "premium": (
            "🚫 <b>Похоже, музыка в профиле требует Telegram Premium "
            "(или недоступна для аккаунта).</b>\n<code>{err}</code>"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "YandexMusicToken",
                None,
                "Токен Яндекс Музыки. "
                "https://yandex-music.readthedocs.io/en/main/token.html",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "check_interval",
                20,
                "Как часто проверять играющий трек, сек (10–300).",
                validator=loader.validators.Integer(minimum=10, maximum=300),
            ),
            loader.ConfigValue(
                "clear_when_idle",
                True,
                "Снимать трек с профиля, когда в очереди Яндекса ничего нет.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "clear_on_pause",
                False,
                "Снимать трек с профиля на паузе (по умолчанию пауза профиль не трогает).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "with_cover",
                True,
                "Прикреплять обложку трека к аудио (видна в профиле).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "bitrate",
                192,
                "Битрейт скачиваемого mp3 (128/192/320).",
                validator=loader.validators.Choice([128, 192, 320]),
            ),
        )
        self.client_ym = None
        # текущий поставленный документ: dict(id, access_hash, file_reference_hex)
        self._current = None

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.dyaprofile_loop.interval = self.config["check_interval"]
        self._current = self.get("current", None)
        await self._init_ym()

    async def _init_ym(self) -> bool:
        token = self.config["YandexMusicToken"]
        if not token:
            logger.error("YandexMusicToken не установлен")
            return False
        try:
            self.client_ym = ClientAsync(token)
            await self.client_ym.init()
            return bool(await self.client_ym.account_status())
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка инициализации Яндекс.Музыки: {e}")
            self.client_ym = None
            return False

    async def _get_track(self):
        """Возвращает данные играющего трека или None (учитывает паузу)."""
        if not self.client_ym and not await self._init_ym():
            return None
        try:
            respond = await get_current_track(
                self.client_ym, self.config["YandexMusicToken"]
            )
            if not respond.get("success") or not respond.get("track"):
                return None
            track = respond["track"][0]
            artists = [a.name for a in getattr(track, "artists", [])]
            albums = getattr(track, "albums", [])
            cover_uri = getattr(track, "cover_uri", None)
            cover = (
                "https://" + cover_uri.replace("%%", "400x400") if cover_uri else ""
            )
            return {
                "obj": track,
                "track_id": str(track.id),
                "title": getattr(track, "title", "Unknown"),
                "artists": artists or ["Unknown"],
                "album": albums[0].title if albums and getattr(albums[0], "title", None) else "",
                "duration_ms": _to_int(getattr(track, "duration_ms", 0))
                or _to_int(respond.get("duration_ms", 0)),
                "cover": cover,
                "paused": bool(respond.get("paused")),
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка получения трека: {e}")
            self.client_ym = None
            return None

    async def _download_cover(self, url: str):
        if not url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    thumb = io.BytesIO(await resp.read())
                    thumb.name = "cover.jpg"
                    return thumb
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Обложку скачать не удалось: {e}")
            return None

    async def _upload_audio(self, track: dict) -> InputDocument:
        """Скачивает mp3 из Яндекса, заливает в Saved Messages как аудио,
        возвращает InputDocument для account.saveMusic."""
        audio = await track["obj"].download_bytes_async(
            codec="mp3", bitrate_in_kbps=int(self.config["bitrate"])
        )
        buf = io.BytesIO(audio)
        buf.name = f"{track['title']}.mp3"
        performer = ", ".join(track["artists"])
        attrs = [
            DocumentAttributeAudio(
                duration=max(0, track["duration_ms"] // 1000),
                title=track["title"],
                performer=performer,
            )
        ]
        thumb = (
            await self._download_cover(track["cover"])
            if self.config["with_cover"]
            else None
        )
        msg = await self.client.send_file(
            "me",
            buf,
            attributes=attrs,
            thumb=thumb,
            force_document=False,
            silent=True,
            caption="🎧 DragoYaProfile",
        )
        doc = msg.document
        # сообщение-носитель в Избранном больше не нужно — профиль хранит копию
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
        return telethon.utils.get_input_document(doc)

    def _input_doc_from_saved(self, saved: dict) -> InputDocument:
        return InputDocument(
            id=saved["id"],
            access_hash=saved["access_hash"],
            file_reference=bytes.fromhex(saved["file_reference"]),
        )

    async def _unsave_current(self):
        """Снимает ранее поставленный трек с профиля (если был)."""
        if not self._current:
            return
        try:
            await self.client(
                SaveMusicRequest(
                    id=self._input_doc_from_saved(self._current), unsave=True
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Не удалось снять прошлый трек: {e}")
        self._current = None
        self.set("current", None)

    async def _set_profile(self, track: dict):
        """Ставит трек в профиль: снимает прошлый, заливает новый, saveMusic."""
        input_doc = await self._upload_audio(track)
        await self.client(SaveMusicRequest(id=input_doc))
        await self._unsave_current()  # убираем предыдущий, оставляя только новый
        self._current = {
            "id": input_doc.id,
            "access_hash": input_doc.access_hash,
            "file_reference": input_doc.file_reference.hex(),
            "track_id": track["track_id"],
        }
        self.set("current", self._current)

    @loader.loop(interval=20, autostart=True)
    async def dyaprofile_loop(self):
        if self.dyaprofile_loop.interval != self.config["check_interval"]:
            self.dyaprofile_loop.interval = self.config["check_interval"]
        if not self.get("enabled", False) or not _HAS_SAVE_MUSIC:
            return
        if not self.config["YandexMusicToken"]:
            return
        try:
            track = await self._get_track()
            if not track:
                # в очереди Яндекса ничего нет — по желанию чистим профиль
                if self.config["clear_when_idle"]:
                    await self._unsave_current()
                return
            if track["paused"] and self.config["clear_on_pause"]:
                await self._unsave_current()
                return
            if self._current and track["track_id"] == self._current.get("track_id"):
                return  # тот же трек уже в профиле
            await self._set_profile(track)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка в dyaprofile_loop: {e}")

    @loader.command(
        ru_doc="🎧 Вкл/выкл авто-синхронизацию музыки профиля", alias="yaprofile"
    )
    async def dyaprofilecmd(self, message):
        """🎧 Toggle syncing current Yandex track to profile music"""
        if not _HAS_SAVE_MUSIC:
            return await utils.answer(message, self.strings("no_api"))
        state = not self.get("enabled", False)
        if state:
            if not self.config["YandexMusicToken"]:
                return await utils.answer(message, self.strings("no_token"))
            if not await self._init_ym():
                return await utils.answer(message, self.strings("auth_fail"))
        self.set("enabled", state)
        await utils.answer(
            message, self.strings("enabled" if state else "disabled")
        )

    @loader.command(ru_doc="🎯 Поставить текущий трек в профиль прямо сейчас")
    async def dyanowcmd(self, message):
        """🎯 Set the currently playing track to profile music right now"""
        if not _HAS_SAVE_MUSIC:
            return await utils.answer(message, self.strings("no_api"))
        if not await self._init_ym():
            return await utils.answer(message, self.strings("auth_fail"))
        track = await self._get_track()
        if not track:
            return await utils.answer(message, self.strings("nothing"))
        msg = await utils.answer(message, self.strings("wait"))
        try:
            await self._set_profile(track)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Ошибка ручной установки: {e}")
            return await utils.answer(
                msg, self.strings("premium").format(err=utils.escape_html(str(e)))
            )
        await utils.answer(
            msg,
            self.strings("set").format(
                title=utils.escape_html(track["title"]),
                artists=utils.escape_html(", ".join(track["artists"])),
            ),
        )

    @loader.command(ru_doc="🧹 Снять трек с профиля")
    async def dyaclearcmd(self, message):
        """🧹 Remove the track from profile music"""
        if not _HAS_SAVE_MUSIC:
            return await utils.answer(message, self.strings("no_api"))
        await self._unsave_current()
        await utils.answer(message, self.strings("cleared"))

    @loader.command(ru_doc="🔎 Проверить авторизацию в Яндекс.Музыке")
    async def dyapcheckcmd(self, message):
        """🔎 Check Yandex.Music authorization"""
        ok = await self._init_ym()
        await utils.answer(message, self.strings("auth_ok" if ok else "auth_fail"))
