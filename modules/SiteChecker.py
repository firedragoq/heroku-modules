__version__ = (2, 2, 0)
# changelog: премиум-эмодзи статусов по умолчанию

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
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=UA) as session:
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
                return {"ok": code < 400, "code": code, "ms": ms, "error": None}
        except asyncio.TimeoutError:
            return {"ok": False, "code": None, "ms": None, "error": "таймаут"}
        except aiohttp.ClientConnectorError:
            return {"ok": False, "code": None, "ms": None, "error": "нет соединения / DNS"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "code": None, "ms": None, "error": type(e).__name__}

    def _fmt_result(self, url: str, res: dict) -> str:
        if res["ok"]:
            return (
                f"{self._icon('up')} <b>{utils.escape_html(_host(url))}</b> — "
                f"<code>{res['code']}</code>, {res['ms']} мс"
            )
        reason = res["error"] or f"HTTP {res['code']}"
        return (
            f"{self._icon('down')} <b>{utils.escape_html(_host(url))}</b> — "
            f"<code>{utils.escape_html(reason)}</code>"
        )

    # ───────────────────── фоновый мониторинг ─────────────────────
    @loader.loop(interval=300, autostart=True)
    async def monitor_loop(self):
        want = int(self.config["check_interval"]) * 60
        if self.monitor_loop.interval != want:
            self.monitor_loop.interval = want
        if not self.get("monitoring", False):
            return
        sites = self.get("sites", {})
        if not sites:
            return
        for url, info in sites.items():
            res = await self._check(url)
            new_status = "up" if res["ok"] else "down"
            old_status = info.get("status", "unknown")
            info["code"] = res["code"]
            info["ms"] = res["ms"]
            info["error"] = res["error"]
            if new_status != old_status:
                prev_since = info.get("since", 0)
                info["status"] = new_status
                info["since"] = int(time.time())
                # уведомляем только о реальных переходах up<->down
                if old_status in ("up", "down"):
                    await self._notify(url, new_status, res, prev_since)
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
            elif info.get("status") == "down":
                extra = f" · {utils.escape_html(info.get('error') or '')} · {_ago(info.get('since'))}"
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
