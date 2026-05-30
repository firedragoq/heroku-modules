__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: psutil

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoFetch — красивая системная инфа (fastfetch/neofetch)     ║
# ║  + живые метрики CPU/RAM/Disk через psutil.                    ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging
import platform
import re
import shutil
import time
from html import escape

import psutil

from .. import loader, utils

logger = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# иконки для полей вывода fastfetch/neofetch (по подстроке ключа)
_FIELD_ICONS = {
    "os": "🖥",
    "host": "🏠",
    "kernel": "🐧",
    "uptime": "⏱",
    "packages": "📦",
    "shell": "🐚",
    "resolution": "🖼",
    "de": "🪟",
    "wm": "🪟",
    "theme": "🎨",
    "icons": "🌟",
    "terminal": "💻",
    "cpu": "⚙️",
    "gpu": "🎮",
    "memory": "🧠",
    "swap": "💱",
    "disk": "💾",
    "local ip": "🌐",
    "battery": "🔋",
    "locale": "🌍",
    "board": "🔌",
    "bios": "📟",
    "ram": "🧠",
}


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ПБ"


def _fmt_uptime(seconds: int) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    parts.append(f"{m}м")
    return " ".join(parts)


def _icon_for(key: str) -> str:
    k = key.lower()
    for sub, icon in _FIELD_ICONS.items():
        if sub in k:
            return icon
    return "•"


@loader.tds
class DragoFetchMod(loader.Module):
    """🖥 Системная инфа через fastfetch/neofetch + живые метрики."""

    strings = {
        "name": "DragoFetch",
        "no_tool": (
            "🚫 <b>Не найден</b> <code>fastfetch</code>/<code>neofetch</code> "
            "<b>на сервере.</b> Покажу встроенную сводку."
        ),
        "loading": "🖥 <b>Собираю системную информацию…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    strings_ru = {
        "_cls_doc": "🖥 Системная инфа через fastfetch/neofetch + живые метрики.",
        "no_tool": (
            "🚫 <b>Не найден</b> <code>fastfetch</code>/<code>neofetch</code> "
            "<b>на сервере.</b> Покажу встроенную сводку."
        ),
        "loading": "🖥 <b>Собираю системную информацию…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "tool",
                "auto",
                "Инструмент: auto / fastfetch / neofetch / builtin.",
                validator=loader.validators.Choice(
                    ["auto", "fastfetch", "neofetch", "builtin"]
                ),
            ),
            loader.ConfigValue(
                "show_bars",
                True,
                "Показывать живые метрики CPU/RAM/Disk с прогресс-барами.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "title_emoji",
                "💻",
                "Эмодзи заголовка (можно премиум — шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    # ───────────────────── сбор данных ─────────────────────
    async def _run(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return _strip_ansi(out.decode("utf-8", "replace"))

    @staticmethod
    def _parse_kv(text: str) -> list[tuple[str, str]]:
        """Парсит строки 'Ключ: Значение' из вывода fastfetch/neofetch."""
        rows: list[tuple[str, str]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            # отсекаем мусор/ASCII-арт (ключ должен быть коротким текстом)
            if value and 1 <= len(key) <= 24 and not key.startswith(("─", "│", "╭")):
                rows.append((key, value))
        return rows

    async def _collect_tool(self) -> tuple[str, list[tuple[str, str]]]:
        tool = self.config["tool"]
        order = (
            [tool]
            if tool in ("fastfetch", "neofetch")
            else ["fastfetch", "neofetch"]
        )
        if tool == "builtin":
            return "", []
        for t in order:
            if not shutil.which(t):
                continue
            try:
                if t == "fastfetch":
                    raw = await self._run("fastfetch", "--logo", "none", "--pipe")
                else:
                    raw = await self._run("neofetch", "--stdout")
                rows = self._parse_kv(raw)
                if rows:
                    return t, rows
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s failed: %s", t, exc)
        return "", []

    def _builtin_rows(self) -> list[tuple[str, str]]:
        uname = platform.uname()
        return [
            ("OS", f"{uname.system} {uname.release}"),
            ("Host", uname.node),
            ("Kernel", uname.version.split()[0] if uname.version else uname.release),
            ("Uptime", _fmt_uptime(time.time() - psutil.boot_time())),
            ("CPU", f"{platform.processor() or uname.machine} ({psutil.cpu_count()} ядер)"),
            ("Python", platform.python_version()),
        ]

    def _metrics_block(self) -> str:
        cpu = psutil.cpu_percent(interval=0.3)
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        up = _fmt_uptime(time.time() - psutil.boot_time())
        lines = [
            "",
            "📊 <b>Живые метрики:</b>",
            f"⚙️ CPU  <code>{_bar(cpu)}</code> {cpu:.0f}%",
            f"🧠 RAM  <code>{_bar(vm.percent)}</code> "
            f"{_human(vm.used)} / {_human(vm.total)} ({vm.percent:.0f}%)",
            f"💾 Disk <code>{_bar(du.percent)}</code> "
            f"{_human(du.used)} / {_human(du.total)} ({du.percent:.0f}%)",
            f"⏱ Uptime: <b>{up}</b>",
        ]
        return "\n".join(lines)

    def _render(self, tool: str, rows: list[tuple[str, str]]) -> str:
        host = platform.uname().node
        title_emoji = self.config["title_emoji"]
        head = f"{title_emoji} <b>Система</b> · <code>{escape(host)}</code>"
        if tool:
            head += f"  <i>({tool})</i>"
        parts = [head, ""]
        for key, value in rows:
            parts.append(
                f"{_icon_for(key)} <b>{escape(key)}:</b> {escape(value)}"
            )
        if self.config["show_bars"]:
            parts.append(self._metrics_block())
        return "\n".join(parts)

    # ───────────────────── команды ─────────────────────
    @loader.command(ru_doc="Показать системную инфу (карточка)", alias="ff")
    async def fetchcmd(self, message):
        """Show system info card"""
        msg = await utils.answer(message, self.strings("loading"))
        try:
            tool, rows = await self._collect_tool()
            if not rows:
                rows = self._builtin_rows()
            await utils.answer(msg, self._render(tool, rows))
        except Exception as exc:  # noqa: BLE001
            logger.exception("fetch failed: %s", exc)
            await utils.answer(msg, self.strings("fail").format(escape(str(exc))))

    @loader.command(ru_doc="Сырой вывод fastfetch/neofetch", alias="ffr")
    async def fetchrawcmd(self, message):
        """Raw fastfetch/neofetch output"""
        tool = self.config["tool"]
        candidates = (
            [tool] if tool in ("fastfetch", "neofetch") else ["fastfetch", "neofetch"]
        )
        for t in candidates:
            if not shutil.which(t):
                continue
            try:
                if t == "fastfetch":
                    raw = await self._run("fastfetch", "--logo", "none", "--pipe")
                else:
                    raw = await self._run("neofetch", "--stdout")
                return await utils.answer(
                    message,
                    f"🖥 <b>{t}</b>\n<pre>{escape(raw.strip()[:3800])}</pre>",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s raw failed: %s", t, exc)
        await utils.answer(message, self.strings("no_tool"))
