__version__ = (1, 1, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp
# changelog: инлайн-режим (use_inline) — ответ через инлайн-бота

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoWeather — погода по городу через wttr.in (без ключа).    ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import re

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )

API = "https://wttr.in/{city}?format=j1&lang=ru"

# эмодзи по коду погоды wttr.in (WWO codes)
_CODE_EMOJI = {
    "113": "☀️",   # Sunny/Clear
    "116": "🌤",   # Partly cloudy
    "119": "☁️",   # Cloudy
    "122": "☁️",   # Overcast
    "143": "🌫",   # Mist
    "176": "🌦",   # Patchy rain
    "179": "🌨",   # Patchy snow
    "182": "🌧",   # Patchy sleet
    "185": "🌧",
    "200": "⛈",   # Thundery
    "227": "🌬",   # Blowing snow
    "230": "❄️",   # Blizzard
    "248": "🌫",   # Fog
    "260": "🌫",
    "263": "🌦", "266": "🌦", "281": "🌧", "284": "🌧",
    "293": "🌦", "296": "🌧", "299": "🌧", "302": "🌧",
    "305": "🌧", "308": "🌧", "311": "🌧",
    "323": "🌨", "326": "🌨", "329": "❄️", "332": "❄️",
    "335": "❄️", "338": "❄️", "350": "🌨",
    "353": "🌦", "356": "🌧", "359": "🌧",
    "362": "🌨", "365": "🌨", "368": "🌨", "371": "❄️",
    "386": "⛈", "389": "⛈", "392": "⛈", "395": "❄️",
}


def _weather_emoji(code: str) -> str:
    return _CODE_EMOJI.get(str(code), "🌡")


@loader.tds
class DragoWeatherMod(loader.Module):
    """🌤 Погода по городу (wttr.in, без API-ключа)."""

    strings = {
        "name": "DragoWeather",
        "no_city": "🚫 <b>Укажи город.</b> Пример: <code>{}weather Москва</code>",
        "loading": "🌤 <b>Узнаю погоду…</b>",
        "not_found": "🚫 <b>Город не найден.</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "card": (
            "{wemoji} <b>{place}</b>\n"
            "<i>{desc}</i>\n\n"
            "{e_temp} <b>Температура:</b> {temp}°C (ощущается {feels}°C)\n"
            "{e_hum} <b>Влажность:</b> {hum}%\n"
            "{e_wind} <b>Ветер:</b> {wind} км/ч {winddir}\n"
            "{e_press} <b>Давление:</b> {press} гПа\n"
            "{e_vis} <b>Видимость:</b> {vis} км\n"
            "{e_fc} <b>Сегодня:</b> {tmin}…{tmax}°C, восход {sunrise}, закат {sunset}"
        ),
    }

    strings_ru = {
        "_cls_doc": "🌤 Погода по городу (wttr.in, без API-ключа).",
        "no_city": "🚫 <b>Укажи город.</b> Пример: <code>{}weather Москва</code>",
        "loading": "🌤 <b>Узнаю погоду…</b>",
        "not_found": "🚫 <b>Город не найден.</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "card": (
            "{wemoji} <b>{place}</b>\n"
            "<i>{desc}</i>\n\n"
            "{e_temp} <b>Температура:</b> {temp}°C (ощущается {feels}°C)\n"
            "{e_hum} <b>Влажность:</b> {hum}%\n"
            "{e_wind} <b>Ветер:</b> {wind} км/ч {winddir}\n"
            "{e_press} <b>Давление:</b> {press} гПа\n"
            "{e_vis} <b>Видимость:</b> {vis} км\n"
            "{e_fc} <b>Сегодня:</b> {tmin}…{tmax}°C, восход {sunrise}, закат {sunset}"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "default_city",
                "Moscow",
                "Город по умолчанию (если не указан в команде).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_temp", "🌡", "Эмодзи температуры. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_humidity", "💧", "Эмодзи влажности. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_wind", "🌬", "Эмодзи ветра. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_pressure", "📊", "Эмодзи давления. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_visibility", "👁", "Эмодзи видимости. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_forecast", "📅", "Эмодзи прогноза. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять ответ через инлайн-бота (от бота, а не аккаунта).",
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

    async def _fetch(self, city: str) -> dict | None:
        timeout = aiohttp.ClientTimeout(total=20)
        url = API.format(city=city)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "curl/8"}) as resp:
                if resp.status != 200:
                    return None
                try:
                    return await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    return None

    @loader.command(ru_doc="<город> — узнать погоду", alias="w")
    async def weathercmd(self, message):
        """<city> — get weather"""
        city = utils.get_args_raw(message).strip() or self.config["default_city"]
        if not city:
            return await self._reply(
                message, self.strings("no_city").format(self.get_prefix())
            )
        await self._status(message, self.strings("loading"))
        try:
            data = await self._fetch(city)
        except Exception as exc:  # noqa: BLE001
            logger.exception("weather failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(exc))
        if not data or not data.get("current_condition"):
            return await self._reply(message, self.strings("not_found"))

        cur = data["current_condition"][0]
        area = (data.get("nearest_area") or [{}])[0]
        today = (data.get("weather") or [{}])[0]
        astro = (today.get("astronomy") or [{}])[0]

        place_parts = []
        if area.get("areaName"):
            place_parts.append(area["areaName"][0]["value"])
        if area.get("country"):
            place_parts.append(area["country"][0]["value"])
        place = ", ".join(place_parts) or city

        # описание (русское если есть)
        desc = ""
        if cur.get("lang_ru"):
            desc = cur["lang_ru"][0]["value"]
        elif cur.get("weatherDesc"):
            desc = cur["weatherDesc"][0]["value"]

        await self._reply(
            message,
            self.strings("card").format(
                wemoji=_weather_emoji(cur.get("weatherCode", "")),
                place=utils.escape_html(place),
                desc=utils.escape_html(desc.strip()),
                e_temp=self.config["emoji_temp"],
                e_hum=self.config["emoji_humidity"],
                e_wind=self.config["emoji_wind"],
                e_press=self.config["emoji_pressure"],
                e_vis=self.config["emoji_visibility"],
                e_fc=self.config["emoji_forecast"],
                temp=cur.get("temp_C", "?"),
                feels=cur.get("FeelsLikeC", "?"),
                hum=cur.get("humidity", "?"),
                wind=cur.get("windspeedKmph", "?"),
                winddir=utils.escape_html(cur.get("winddir16Point", "")),
                press=cur.get("pressure", "?"),
                vis=cur.get("visibility", "?"),
                tmin=today.get("mintempC", "?"),
                tmax=today.get("maxtempC", "?"),
                sunrise=astro.get("sunrise", "?"),
                sunset=astro.get("sunset", "?"),
            ),
        )
