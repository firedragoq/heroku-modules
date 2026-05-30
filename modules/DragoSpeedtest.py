__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoSpeedtest — тест скорости сети сервера (Cloudflare).     ║
# ║  Download / Upload / Ping без внешних бинарей.                 ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging
import time

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
UP_URL = "https://speed.cloudflare.com/__up"
PING_URL = "https://speed.cloudflare.com/__down?bytes=0"


def _bar(value: float, vmax: float, width: int = 10) -> str:
    if vmax <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * value / vmax)))
    return "█" * filled + "░" * (width - filled)


def _speed_emoji(mbps: float) -> str:
    if mbps >= 100:
        return "🚀"
    if mbps >= 30:
        return "⚡️"
    if mbps >= 5:
        return "🐢"
    return "🦥"


@loader.tds
class DragoSpeedtestMod(loader.Module):
    """🚀 Тест скорости сети сервера (download/upload/ping)."""

    strings = {
        "name": "DragoSpeedtest",
        "running": "🚀 <b>Замеряю скорость сети…</b>\n<i>Это займёт ~10–20 секунд.</i>",
        "fail": "🚫 <b>Ошибка теста:</b> <code>{}</code>",
        "result": (
            "🚀 <b>Тест скорости сети</b>\n\n"
            "{demoji} <b>Download:</b> <code>{down:.1f}</code> Мбит/с\n"
            "<code>{dbar}</code>\n"
            "{uemoji} <b>Upload:</b> <code>{up:.1f}</code> Мбит/с\n"
            "<code>{ubar}</code>\n"
            "📡 <b>Ping:</b> <code>{ping:.0f}</code> мс\n"
            "🌐 <b>Сервер:</b> Cloudflare ({colo})"
        ),
    }

    strings_ru = {
        "_cls_doc": "🚀 Тест скорости сети сервера (download/upload/ping).",
        "running": "🚀 <b>Замеряю скорость сети…</b>\n<i>Это займёт ~10–20 секунд.</i>",
        "fail": "🚫 <b>Ошибка теста:</b> <code>{}</code>",
        "result": (
            "🚀 <b>Тест скорости сети</b>\n\n"
            "{demoji} <b>Download:</b> <code>{down:.1f}</code> Мбит/с\n"
            "<code>{dbar}</code>\n"
            "{uemoji} <b>Upload:</b> <code>{up:.1f}</code> Мбит/с\n"
            "<code>{ubar}</code>\n"
            "📡 <b>Ping:</b> <code>{ping:.0f}</code> мс\n"
            "🌐 <b>Сервер:</b> Cloudflare ({colo})"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "down_mb",
                25,
                "Сколько МБ качать для теста download (5–100).",
                validator=loader.validators.Integer(minimum=5, maximum=100),
            ),
            loader.ConfigValue(
                "up_mb",
                10,
                "Сколько МБ отправлять для теста upload (1–50).",
                validator=loader.validators.Integer(minimum=1, maximum=50),
            ),
            loader.ConfigValue(
                "scale_mbps",
                200,
                "Максимум шкалы прогресс-бара, Мбит/с.",
                validator=loader.validators.Integer(minimum=10, maximum=10000),
            ),
        )

    async def _ping(self, session) -> tuple[float, str]:
        """Средний RTT по нескольким запросам + дата-центр Cloudflare."""
        rtts = []
        colo = "?"
        for _ in range(5):
            t = time.monotonic()
            try:
                async with session.get(PING_URL) as resp:
                    await resp.read()
                    rtts.append((time.monotonic() - t) * 1000)
                    cf = resp.headers.get("cf-meta-colo") or resp.headers.get("cf-ray", "")
                    if cf and colo == "?":
                        colo = cf.split("-")[-1] if "-" in cf else cf
            except Exception:  # noqa: BLE001
                continue
        avg = sum(rtts) / len(rtts) if rtts else 0.0
        return avg, colo

    async def _download(self, session) -> float:
        n = int(self.config["down_mb"]) * 1024 * 1024
        start = time.monotonic()
        got = 0
        async with session.get(DOWN_URL.format(n=n)) as resp:
            async for chunk in resp.content.iter_chunked(65536):
                got += len(chunk)
        dt = time.monotonic() - start
        return (got * 8 / dt / 1_000_000) if dt > 0 else 0.0

    async def _upload(self, session) -> float:
        n = int(self.config["up_mb"]) * 1024 * 1024
        payload = b"\0" * n
        start = time.monotonic()
        async with session.post(UP_URL, data=payload) as resp:
            await resp.read()
        dt = time.monotonic() - start
        return (n * 8 / dt / 1_000_000) if dt > 0 else 0.0

    @loader.command(ru_doc="Замерить скорость сети сервера", alias="spt")
    async def speedtestcmd(self, message):
        """Measure server network speed"""
        msg = await utils.answer(message, self.strings("running"))
        timeout = aiohttp.ClientTimeout(total=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                ping, colo = await self._ping(session)
                down = await self._download(session)
                up = await self._upload(session)
        except Exception as exc:  # noqa: BLE001
            logger.exception("speedtest failed: %s", exc)
            return await utils.answer(message, self.strings("fail").format(exc))

        scale = float(self.config["scale_mbps"])
        await utils.answer(
            msg,
            self.strings("result").format(
                demoji=_speed_emoji(down),
                uemoji=_speed_emoji(up),
                down=down,
                up=up,
                dbar=_bar(down, scale),
                ubar=_bar(up, scale),
                ping=ping,
                colo=colo,
            ),
        )
