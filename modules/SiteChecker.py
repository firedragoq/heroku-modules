__version__ = (2, 5, 0)
# changelog: анти-флаппинг — статус меняется только после N подряд одинаковых
#            проверок (confirm_checks), разовые таймауты больше не флудят

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  SiteChecker — мониторинг доступности сайтов с уведомлениями.  ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging
import time
from urllib.parse import urlparse

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (compatible; SiteChecker/2.0; +https://t.me/dragomodules)"}


def _norm(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _ago(ts: int) -> str:
    if not ts:
        return "—"
    sec = int(time.time()) - int(ts)
    if sec < 60:
        return f"{sec}с"
    if sec < 3600:
        return f"{sec // 60}м"
    if sec < 86400:
        return f"{sec // 3600}ч"
    return f"{sec // 86400}д"


@loader.tds
class SiteCheckerMod(loader.Module):
    """🌐 Мониторинг доступности сайтов с уведомлениями о падении/восстановлении."""

    strings = {
        "name": "SiteChecker",
        "no_url": "🚫 <b>Укажи ссылку.</b> Пример: <code>{}siteadd example.com</code>",
        "added": "✅ <b>Добавлен в мониторинг:</b> {}",
        "exists": "⚠️ <b>Уже в списке:</b> {}",
        "removed": "🗑 <b>Удалён:</b> {}",
        "not_found": "🚫 <b>Не найден в списке.</b>",
        "empty": "📭 <b>Список сайтов пуст.</b> Добавь: <code>{}siteadd &lt;url&gt;</code>",
        "checking": "⏳ <b>Проверяю…</b>",
        "mon_on": "🟢 <b>Мониторинг включён.</b> Интервал: {} мин.",
        "mon_off": "🔴 <b>Мониторинг выключен.</b>",
        "down_alert": "{icon} <b>Сайт недоступен!</b>\n{site} {url}\n⚠️ <code>{reason}</code>",
        "up_alert": "{icon} <b>Сайт снова доступен:</b>\n{site} {url}\n⏱ Был недоступен: {downtime}",
        "list_title": "{site} <b>Сайты в мониторинге ({n}):</b>",
    }

    strings_ru = {
        "_cls_doc": "🌐 Мониторинг доступности сайтов с уведомлениями.",
        "no_url": "🚫 <b>Укажи ссылку.</b> Пример: <code>{}siteadd example.com</code>",
        "added": "✅ <b>Добавлен в мониторинг:</b> {}",
        "exists": "⚠️ <b>Уже в списке:</b> {}",
        "removed": "🗑 <b>Удалён:</b> {}",
        "not_found": "🚫 <b>Не найден в списке.</b>",
        "empty": "📭 <b>Список сайтов пуст.</b> Добавь: <code>{}siteadd &lt;url&gt;</code>",
        "checking": "⏳ <b>Проверяю…</b>",
        "mon_on": "🟢 <b>Мониторинг включён.</b> Интервал: {} мин.",
        "mon_off": "🔴 <b>Мониторинг выключен.</b>",
        "down_alert": "{icon} <b>Сайт недоступен!</b>\n{site} {url}\n⚠️ <code>{reason}</code>",
        "up_alert": "{icon} <b>Сайт снова доступен:</b>\n{site} {url}\n⏱ Был недоступен: {downtime}",
        "list_title": "{site} <b>Сайты в мониторинге ({n}):</b>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "check_interval",
                5,
                "Интервал фоновой проверки, минут (1–1440).",
                validator=loader.validators.Integer(minimum=1, maximum=1440),
            ),
            loader.ConfigValue(
                "timeout",
                15,
                "Таймаут запроса, секунд (1–60).",
                validator=loader.validators.Integer(minimum=1, maximum=60),
            ),
            loader.ConfigValue(
                "confirm_checks",
                2,
                "Сколько проверок подряд должны совпасть, чтобы сменить статус и "
                "прислать алерт (анти-флаппинг). 1 = реагировать мгновенно.",
                validator=loader.validators.Integer(minimum=1, maximum=10),
            ),
            loader.ConfigValue(
                "notify_chat",
                "me",
                "Куда слать уведомления: 'me' (Избранное) или id чата/канала.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "alert_recovery",
                True,
                "Уведомлять, когда сайт снова поднялся.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "keyword",
                "",
                "Если задано — сайт считается рабочим, только если это слово есть "
                "в HTML страницы (защита от заглушек). Пусто = проверять только код.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "slow_ms",
                0,
                "Порог «медленно», мс (0 = выкл). Если ответ дольше — помечается ⚠️.",
                validator=loader.validators.Integer(minimum=0, maximum=60000),
            ),
            loader.ConfigValue(
                "emoji_up",
                "<emoji document_id=5416081784641168838>🟢</emoji>",
                "Иконка «доступен». Можно вставить премиум-эмодзи (emoji-тег с числовым document_id).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_down",
                "<emoji document_id=5411225014148014586>🔴</emoji>",
                "Иконка «недоступен». Можно вставить премиум-эмодзи.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_unknown",
                "<emoji document_id=5386367538735104399>⌛️</emoji>",
                "Иконка «не проверялся». Можно премиум-эмодзи.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_site",
                "<emoji document_id=5447410659077661506>🌐</emoji>",
                "Иконка сайта/заголовка. Можно премиум-эмодзи.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_bell",
                "<emoji document_id=5458603043203327669>🔔</emoji>",
                "Иконка звоночка (строка мониторинга). Можно премиум-эмодзи.",
                validator=loader.validators.String(),
            ),
        )

    async def client_ready(self, client, db):
        self.client = client
        self.db = db
        self.monitor_loop.interval = int(self.config["check_interval"]) * 60

    def _icon(self, status: str) -> str:
        return {
            "up": self.config["emoji_up"],
            "down": self.config["emoji_down"],
        }.get(status, self.config["emoji_unknown"])

    # ───────────────────── проверка ─────────────────────
    async def _check(self, url: str) -> dict:
        timeout = aiohttp.ClientTimeout(total=int(self.config["timeout"]))
        keyword = (self.config["keyword"] or "").strip()
        slow_ms = int(self.config["slow_ms"])
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=UA) as session:
                if keyword:
                    # нужно тело страницы — только GET
                    resp = await session.get(url, allow_redirects=True)
                    body = await resp.text(errors="ignore")
                else:
                    body = ""
                    # HEAD быстрее; если сайт его не любит — повторяем GET
                    try:
                        resp = await session.head(url, allow_redirects=True)
                        if resp.status in (403, 405, 501):
                            resp = await session.get(url, allow_redirects=True)
                    except aiohttp.ClientError:
                        resp = await session.get(url, allow_redirects=True)
                ms = int((time.monotonic() - start) * 1000)
                code = resp.status
                resp.close()
                ok = code < 400
                error = None
                if ok and keyword and keyword.lower() not in body.lower():
                    ok = False
                    error = "нет ключевого слова"
                slow = bool(ok and slow_ms and ms > slow_ms)
                return {"ok": ok, "code": code, "ms": ms, "error": error, "slow": slow}
        except asyncio.TimeoutError:
            return {"ok": False, "code": None, "ms": None, "error": "таймаут", "slow": False}
        except aiohttp.ClientConnectorError:
            return {"ok": False, "code": None, "ms": None, "error": "нет соединения / DNS", "slow": False}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "code": None, "ms": None, "error": type(e).__name__, "slow": False}

    @staticmethod
    def _record_stats(info: dict, res: dict) -> None:
        """Накопление статистики аптайма по сайту."""
        info["checks"] = info.get("checks", 0) + 1
        if res["ok"]:
            info["up_count"] = info.get("up_count", 0) + 1

    @staticmethod
    def _uptime(info: dict) -> str:
        checks = info.get("checks", 0)
        if not checks:
            return "—"
        pct = 100 * info.get("up_count", 0) / checks
        return f"{pct:.1f}%"

    def _fmt_result(self, url: str, res: dict) -> str:
        if res["ok"]:
            slow = " ⚠️ медленно" if res.get("slow") else ""
            return (
                f"{self._icon('up')} <b>{utils.escape_html(_host(url))}</b> — "
                f"<code>{res['code']}</code>, {res['ms']} мс{slow}"
            )
        reason = res["error"] or f"HTTP {res['code']}"
        return (
            f"{self._icon('down')} <b>{utils.escape_html(_host(url))}</b> — "
            f"<code>{utils.escape_html(reason)}</code>"
        )

    # ───────────────────── фоновый мониторинг ─────────────────────
    @loader.loop(interval=60, autostart=True)
    async def monitor_loop(self):
        # тикаем раз в минуту; для каждого сайта смотрим его персональный
        # интервал (info["interval"]) или глобальный check_interval
        if not self.get("monitoring", False):
            return
        sites = self.get("sites", {})
        if not sites:
            return
        now = int(time.time())
        default_int = int(self.config["check_interval"])
        confirm = max(1, int(self.config["confirm_checks"]))
        for url, info in sites.items():
            every = int(info.get("interval") or default_int) * 60
            if now - info.get("last_check", 0) < every:
                continue
            info["last_check"] = now
            res = await self._check(url)
            raw = "up" if res["ok"] else "down"
            info["code"] = res["code"]
            info["ms"] = res["ms"]
            info["error"] = res["error"]
            info["slow"] = res.get("slow", False)
            self._record_stats(info, res)

            status = info.get("status", "unknown")
            if raw == status:
                # состояние стабильно — сбрасываем накопленный «переход»
                info["streak"] = 0
                info["pending"] = raw
                continue
            # копим подтверждения, прежде чем менять статус и слать алерт
            if info.get("pending") == raw:
                info["streak"] = int(info.get("streak", 0)) + 1
            else:
                info["pending"] = raw
                info["streak"] = 1
            if info["streak"] >= confirm:
                prev_since = info.get("since", 0)
                info["status"] = raw
                info["since"] = now
                info["streak"] = 0
                # уведомляем только о реальных переходах up<->down
                if status in ("up", "down"):
                    await self._notify(url, raw, res, prev_since)
        self.set("sites", sites)

    async def _notify(self, url, status, res, prev_since):
        if status == "up" and not self.config["alert_recovery"]:
            return
        chat = self.config["notify_chat"] or "me"
        target = chat if chat == "me" else int(chat)
        site = self.config["emoji_site"]
        if status == "down":
            text = self.strings("down_alert").format(
                icon=self._icon("down"),
                site=site,
                url=utils.escape_html(url),
                reason=res["error"] or f"HTTP {res['code']}",
            )
        else:
            text = self.strings("up_alert").format(
                icon=self._icon("up"),
                site=site,
                url=utils.escape_html(url),
                downtime=_ago(prev_since),
            )
        try:
            await self.client.send_message(target, text, parse_mode="html")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Не удалось отправить уведомление: {e}")

    # ───────────────────── команды ─────────────────────
    @loader.command(ru_doc="<url> — добавить сайт в мониторинг", alias="sca")
    async def siteaddcmd(self, message):
        """<url> — add a site to monitoring"""
        url = _norm(utils.get_args_raw(message))
        if not url:
            return await utils.answer(message, self.strings("no_url").format(self.get_prefix()))
        sites = self.get("sites", {})
        if url in sites:
            return await utils.answer(message, self.strings("exists").format(url))
        sites[url] = {"status": "unknown", "code": None, "ms": None, "since": 0, "error": None}
        self.set("sites", sites)
        await utils.answer(message, self.strings("added").format(url))

    @loader.command(ru_doc="<url|номер> — убрать сайт из мониторинга", alias="scd")
    async def sitedelcmd(self, message):
        """<url|index> — remove a site from monitoring"""
        arg = utils.get_args_raw(message).strip()
        sites = self.get("sites", {})
        if not sites:
            return await utils.answer(message, self.strings("empty").format(self.get_prefix()))
        target = None
        if arg.isdigit():
            idx = int(arg) - 1
            keys = list(sites)
            if 0 <= idx < len(keys):
                target = keys[idx]
        else:
            cand = _norm(arg)
            if cand in sites:
                target = cand
        if not target:
            return await utils.answer(message, self.strings("not_found"))
        sites.pop(target)
        self.set("sites", sites)
        await utils.answer(message, self.strings("removed").format(target))

    @loader.command(ru_doc="Список сайтов и их статус", alias="scl")
    async def sitescmd(self, message):
        """List monitored sites and their status"""
        sites = self.get("sites", {})
        if not sites:
            return await utils.answer(message, self.strings("empty").format(self.get_prefix()))
        rows = []
        for i, (url, info) in enumerate(sites.items(), 1):
            icon = self._icon(info.get("status", "unknown"))
            extra = ""
            if info.get("status") == "up" and info.get("ms") is not None:
                extra = f" · {info['ms']} мс"
                if info.get("slow"):
                    extra += " ⚠️"
            elif info.get("status") == "down":
                extra = f" · {utils.escape_html(info.get('error') or '')} · {_ago(info.get('since'))}"
            if info.get("checks"):
                extra += f" · ↑{self._uptime(info)}"
            if info.get("interval"):
                extra += f" · ⏱{info['interval']}м"
            rows.append(f"{i}. {icon} <b>{utils.escape_html(_host(url))}</b>{extra}")
        mon = "🟢 вкл" if self.get("monitoring", False) else "🔴 выкл"
        await utils.answer(
            message,
            self.strings("list_title").format(site=self.config["emoji_site"], n=len(sites))
            + f"\n{self.config['emoji_bell']} Мониторинг: {mon} · "
            + f"каждые {self.config['check_interval']} мин\n\n"
            + "\n".join(rows),
        )

    @loader.command(ru_doc="<url> — разово проверить любой сайт", alias="scc")
    async def sitecheckcmd(self, message):
        """<url> — one-off check of any site"""
        url = _norm(utils.get_args_raw(message))
        if not url:
            return await utils.answer(message, self.strings("no_url").format(self.get_prefix()))
        msg = await utils.answer(message, self.strings("checking"))
        res = await self._check(url)
        await utils.answer(msg, self._fmt_result(url, res))

    @loader.command(ru_doc="Проверить все сайты из мониторинга сейчас", alias="scall")
    async def checksitescmd(self, message):
        """Check all monitored sites now"""
        sites = self.get("sites", {})
        if not sites:
            return await utils.answer(message, self.strings("empty").format(self.get_prefix()))
        msg = await utils.answer(message, self.strings("checking"))
        results = await asyncio.gather(*(self._check(u) for u in sites))
        lines = [self._fmt_result(u, r) for u, r in zip(sites, results)]
        # обновим сохранённые статусы
        for (url, info), res in zip(sites.items(), results):
            info["status"] = "up" if res["ok"] else "down"
            info["code"], info["ms"], info["error"] = res["code"], res["ms"], res["error"]
            info["slow"] = res.get("slow", False)
            self._record_stats(info, res)
        self.set("sites", sites)
        await utils.answer(
            msg,
            self.strings("list_title").format(site=self.config["emoji_site"], n=len(sites))
            + "\n\n"
            + "\n".join(lines),
        )

    @loader.command(ru_doc="Вкл/выкл фоновый мониторинг", alias="scm")
    async def sitemoncmd(self, message):
        """Toggle background monitoring"""
        state = not self.get("monitoring", False)
        self.set("monitoring", state)
        if state:
            await utils.answer(
                message, self.strings("mon_on").format(self.config["check_interval"])
            )
        else:
            await utils.answer(message, self.strings("mon_off"))

    @loader.command(ru_doc="<url|номер> <мин> — свой интервал для сайта (0=общий)", alias="sci")
    async def siteintcmd(self, message):
        """<url|index> <min> — per-site check interval (0 = global)"""
        args = utils.get_args_raw(message).split()
        sites = self.get("sites", {})
        if not sites:
            return await utils.answer(message, self.strings("empty").format(self.get_prefix()))
        if len(args) < 2 or not args[-1].isdigit():
            return await utils.answer(
                message,
                "⚠️ <b>Формат:</b> <code>{p}siteint &lt;url|номер&gt; &lt;минуты&gt;</code>\n"
                "0 = использовать общий интервал.".format(p=self.get_prefix()),
            )
        minutes = int(args[-1])
        ident = " ".join(args[:-1]).strip()
        target = None
        if ident.isdigit():
            keys = list(sites)
            idx = int(ident) - 1
            if 0 <= idx < len(keys):
                target = keys[idx]
        else:
            cand = _norm(ident)
            if cand in sites:
                target = cand
        if not target:
            return await utils.answer(message, self.strings("not_found"))
        sites[target]["interval"] = minutes
        self.set("sites", sites)
        if minutes:
            await utils.answer(
                message,
                f"⏱ <b>{utils.escape_html(_host(target))}</b> — интервал "
                f"<b>{minutes} мин</b>.",
            )
        else:
            await utils.answer(
                message,
                f"⏱ <b>{utils.escape_html(_host(target))}</b> — общий интервал "
                f"({self.config['check_interval']} мин).",
            )

    @loader.command(ru_doc="Статистика аптайма по сайтам", alias="scs")
    async def sitestatscmd(self, message):
        """Uptime statistics per site"""
        sites = self.get("sites", {})
        if not sites:
            return await utils.answer(message, self.strings("empty").format(self.get_prefix()))
        rows = []
        for i, (url, info) in enumerate(sites.items(), 1):
            icon = self._icon(info.get("status", "unknown"))
            checks = info.get("checks", 0)
            last = f"{info['ms']} мс" if info.get("ms") is not None else "—"
            rows.append(
                f"{i}. {icon} <b>{utils.escape_html(_host(url))}</b>\n"
                f"   ↑ Аптайм: <b>{self._uptime(info)}</b> "
                f"({info.get('up_count', 0)}/{checks}) · "
                f"последний: {last} · в статусе: {_ago(info.get('since'))}"
            )
        await utils.answer(
            message,
            f"{self.config['emoji_site']} <b>Статистика ({len(sites)}):</b>\n\n"
            + "\n".join(rows),
        )

    @loader.command(ru_doc="Сбросить статистику аптайма", alias="scsr")
    async def sitestatsresetcmd(self, message):
        """Reset uptime statistics"""
        sites = self.get("sites", {})
        for info in sites.values():
            info["checks"] = 0
            info["up_count"] = 0
        self.set("sites", sites)
        await utils.answer(message, "♻️ <b>Статистика аптайма сброшена.</b>")
