__version__ = (1, 2, 1)

# meta developer: @dragomodules
# scope: heroku_only
# requires: psutil pillow
# changelog: фикс — картинка .fetchimg больше не исчезает

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoFetch — красивая системная инфа (fastfetch/neofetch)     ║
# ║  + живые метрики CPU/RAM/Disk через psutil. Можно картинкой.   ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import io
import logging
import platform
import re
import shutil
import time
from html import escape

import psutil

from .. import loader, utils

try:
    from PIL import Image, ImageDraw, ImageFont

    _PIL = True
except ImportError:  # noqa: BLE001
    _PIL = False

_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

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
            loader.ConfigValue(
                "emoji_metrics",
                "📊",
                "Эмодзи заголовка «Живые метрики». Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_cpu",
                "⚙️",
                "Эмодзи CPU. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_ram",
                "🧠",
                "Эмодзи RAM. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_disk",
                "💾",
                "Эмодзи Disk. Можно премиум.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_uptime",
                "⏱",
                "Эмодзи Uptime. Можно премиум.",
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
            f"{self.config['emoji_metrics']} <b>Живые метрики:</b>",
            f"{self.config['emoji_cpu']} CPU  <code>{_bar(cpu)}</code> {cpu:.0f}%",
            f"{self.config['emoji_ram']} RAM  <code>{_bar(vm.percent)}</code> "
            f"{_human(vm.used)} / {_human(vm.total)} ({vm.percent:.0f}%)",
            f"{self.config['emoji_disk']} Disk <code>{_bar(du.percent)}</code> "
            f"{_human(du.used)} / {_human(du.total)} ({du.percent:.0f}%)",
            f"{self.config['emoji_uptime']} Uptime: <b>{up}</b>",
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

    async def _top_procs(self, n: int = 5) -> tuple[list, list]:
        """Топ процессов по CPU и по RAM."""
        procs = list(psutil.process_iter(["name", "memory_percent"]))
        for p in procs:
            try:
                p.cpu_percent(None)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.5)
        data = []
        for p in procs:
            try:
                data.append(
                    (
                        p.info.get("name") or "?",
                        p.cpu_percent(None),
                        p.info.get("memory_percent") or 0.0,
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        by_cpu = sorted(data, key=lambda x: -x[1])[:n]
        by_ram = sorted(data, key=lambda x: -x[2])[:n]
        return by_cpu, by_ram

    # ───────────────────── рендер картинки ─────────────────────
    def _font(self, name: str, size: int):
        try:
            return ImageFont.truetype(_FONT_DIR + name, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    def _render_image(self, tool: str, rows: list[tuple[str, str]]) -> io.BytesIO:
        f_title = self._font("DejaVuSans-Bold.ttf", 30)
        f_key = self._font("DejaVuSansMono-Bold.ttf", 20)
        f_val = self._font("DejaVuSansMono.ttf", 20)

        pad = 32
        line_h = 30
        bar_h = 34
        W = 860
        n_bars = 3 if self.config["show_bars"] else 0
        H = pad + 50 + 14 + len(rows) * line_h + (n_bars * bar_h + 30 if n_bars else 0) + pad

        img = Image.new("RGB", (W, H), (26, 27, 38))
        d = ImageDraw.Draw(img)
        # вертикальный градиент фона
        top, bot = (26, 27, 38), (36, 40, 59)
        for y in range(H):
            t = y / H
            d.line(
                [(0, y), (W, y)],
                fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)),
            )

        accent = (122, 162, 247)
        key_col = (158, 206, 106)
        val_col = (192, 202, 245)
        host = platform.uname().node
        user = ""
        try:
            user = psutil.Process().username().split("\\")[-1]
        except Exception:  # noqa: BLE001
            pass
        title = f"{user}@{host}" if user else host
        d.text((pad, pad), title, font=f_title, fill=accent)
        if tool:
            d.text((pad, pad + 34), tool, font=f_val, fill=(86, 95, 137))

        y = pad + 50 + 14
        d.line([(pad, y - 8), (W - pad, y - 8)], fill=(60, 64, 82), width=2)
        for key, value in rows:
            d.text((pad, y), f"{key}:", font=f_key, fill=key_col)
            d.text((pad + 200, y), value[:70], font=f_val, fill=val_col)
            y += line_h

        if n_bars:
            y += 12
            cpu = psutil.cpu_percent(interval=0.3)
            vm = psutil.virtual_memory()
            du = psutil.disk_usage("/")
            for label, pct in (("CPU", cpu), ("RAM", vm.percent), ("Disk", du.percent)):
                d.text((pad, y), label, font=f_key, fill=key_col)
                bx, bw = pad + 110, W - pad - 110 - 70
                d.rounded_rectangle([bx, y + 2, bx + bw, y + 20], 6, fill=(40, 42, 54))
                col = (
                    (158, 206, 106)
                    if pct < 60
                    else (224, 175, 104)
                    if pct < 85
                    else (247, 118, 142)
                )
                d.rounded_rectangle(
                    [bx, y + 2, bx + int(bw * pct / 100), y + 20], 6, fill=col
                )
                d.text((bx + bw + 12, y), f"{pct:.0f}%", font=f_val, fill=val_col)
                y += bar_h

        buf = io.BytesIO()
        buf.name = "dragofetch.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

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

    @loader.command(ru_doc="Системная инфа карточкой-картинкой", alias="ffi")
    async def fetchimgcmd(self, message):
        """System info as an image card"""
        if not _PIL:
            return await utils.answer(
                message, "🚫 <b>Pillow не установлен.</b> Используй <code>.fetch</code>."
            )
        msg = await utils.answer(message, self.strings("loading"))
        try:
            tool, rows = await self._collect_tool()
            if not rows:
                rows = self._builtin_rows()
            img = self._render_image(tool, rows)
            # заменяем loading-сообщение на картинку (одно сообщение, без мигания)
            await utils.answer(
                msg,
                f"{self.config['title_emoji']} <b>Система</b> · "
                f"<code>{escape(platform.uname().node)}</code>",
                file=img,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("fetchimg failed: %s", exc)
            await utils.answer(msg, self.strings("fail").format(escape(str(exc))))

    @loader.command(ru_doc="Топ процессов по CPU и RAM", alias="tp")
    async def topproccmd(self, message):
        """Top processes by CPU and RAM"""
        msg = await utils.answer(message, "📊 <b>Собираю процессы…</b>")
        by_cpu, by_ram = await self._top_procs()
        lines = [
            f"{self.config['emoji_metrics']} <b>Топ процессов</b>\n",
            f"{self.config['emoji_cpu']} <b>По CPU:</b>",
        ]
        for name, cpu, _ in by_cpu:
            lines.append(f"• <code>{escape(name)}</code> — {cpu:.0f}%")
        lines.append(f"\n{self.config['emoji_ram']} <b>По RAM:</b>")
        for name, _, mem in by_ram:
            lines.append(f"• <code>{escape(name)}</code> — {mem:.1f}%")
        await utils.answer(msg, "\n".join(lines))

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
