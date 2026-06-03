__version__ = (1, 0, 0)

# meta developer: @dragomodules
# meta category: Сеть и сайты
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoWhois — инфо по домену и IP (whois, гео, провайдер).     ║
# ║  Без API-ключей.                                               ║
# ╚══════════════════════════════════════════════════════════════╝

import logging
import re

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

RDAP = "https://rdap.org/domain/{domain}"
IPAPI = "http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,regionName,city,isp,org,as,query,reverse,timezone,mobile,proxy,hosting&lang=ru"

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_CLEAN = re.compile(r"^https?://", re.IGNORECASE)


@loader.tds
class DragoWhoisMod(loader.Module):
    """🌐 Инфо по домену и IP: whois, гео, провайдер (без ключей)."""

    strings = {
        "name": "DragoWhois",
        "no_arg": (
            "{emoji} <b>Укажи домен или IP.</b>\n"
            "<code>{p}whois example.com</code> · <code>{p}ip 8.8.8.8</code>"
        ),
        "loading": "{emoji} <b>Запрашиваю данные…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "not_found": "🚫 <b>Ничего не найдено по</b> <code>{}</code>.",
        "domain_card": (
            "{emoji} <b>Домен:</b> <code>{domain}</code>\n\n"
            "{e_reg} <b>Регистратор:</b> {registrar}\n"
            "{e_status} <b>Статус:</b> {status}\n"
            "{e_date} <b>Создан:</b> {created}\n"
            "{e_date} <b>Истекает:</b> {expires}\n"
            "{e_ns} <b>NS:</b>\n{ns}"
        ),
        "ip_card": (
            "{emoji} <b>IP:</b> <code>{ip}</code>\n\n"
            "{e_geo} <b>Гео:</b> {country} ({cc}), {region}, {city}\n"
            "{e_isp} <b>Провайдер:</b> {isp}\n"
            "{e_org} <b>Организация:</b> {org}\n"
            "{e_as} <b>AS:</b> {asn}\n"
            "{e_rev} <b>PTR:</b> <code>{reverse}</code>\n"
            "{e_tz} <b>Таймзона:</b> {timezone}\n"
            "{flags}"
        ),
    }

    strings_ru = {
        "_cls_doc": "🌐 Инфо по домену и IP: whois, гео, провайдер (без ключей).",
        "whoiscmd_doc": "<домен> — whois домена",
        "ipcmd_doc": "<ip> — гео и провайдер IP",
        "no_arg": (
            "{emoji} <b>Укажи домен или IP.</b>\n"
            "<code>{p}whois example.com</code> · <code>{p}ip 8.8.8.8</code>"
        ),
        "loading": "{emoji} <b>Запрашиваю данные…</b>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "not_found": "🚫 <b>Ничего не найдено по</b> <code>{}</code>.",
        "domain_card": (
            "{emoji} <b>Домен:</b> <code>{domain}</code>\n\n"
            "{e_reg} <b>Регистратор:</b> {registrar}\n"
            "{e_status} <b>Статус:</b> {status}\n"
            "{e_date} <b>Создан:</b> {created}\n"
            "{e_date} <b>Истекает:</b> {expires}\n"
            "{e_ns} <b>NS:</b>\n{ns}"
        ),
        "ip_card": (
            "{emoji} <b>IP:</b> <code>{ip}</code>\n\n"
            "{e_geo} <b>Гео:</b> {country} ({cc}), {region}, {city}\n"
            "{e_isp} <b>Провайдер:</b> {isp}\n"
            "{e_org} <b>Организация:</b> {org}\n"
            "{e_as} <b>AS:</b> {asn}\n"
            "{e_rev} <b>PTR:</b> <code>{reverse}</code>\n"
            "{e_tz} <b>Таймзона:</b> {timezone}\n"
            "{flags}"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "emoji_net",
                "🌐",
                "Эмодзи заголовка. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    async def _get_json(self, url: str):
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {"User-Agent": "DragoWhois", "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(url) as r:
                return r.status, await r.json(content_type=None)

    @staticmethod
    def _events(data: dict, action: str) -> str:
        for ev in data.get("events", []) or []:
            if ev.get("eventAction") == action:
                return (ev.get("eventDate", "") or "")[:10]
        return "—"

    @loader.command(ru_doc="<домен> — whois домена", alias="domain")
    async def whoiscmd(self, message):
        """<domain> — domain whois"""
        emoji = self.config["emoji_net"]
        arg = utils.get_args_raw(message).strip().lower()
        arg = _CLEAN.sub("", arg).split("/")[0]
        if not arg:
            return await utils.answer(
                message, self.strings("no_arg").format(emoji=emoji, p=self.get_prefix())
            )
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            status, data = await self._get_json(RDAP.format(domain=arg))
            if status >= 400 or not isinstance(data, dict) or "ldhName" not in data:
                return await utils.answer(message, self.strings("not_found").format(
                    utils.escape_html(arg)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("whois failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(
                utils.escape_html(str(exc))))

        registrar = "—"
        for ent in data.get("entities", []) or []:
            if "registrar" in (ent.get("roles") or []):
                vcard = ent.get("vcardArray", [])
                if len(vcard) > 1:
                    for item in vcard[1]:
                        if item and item[0] == "fn":
                            registrar = item[3]
                            break
        statuses = ", ".join(data.get("status", []) or []) or "—"
        ns_list = [n.get("ldhName", "") for n in data.get("nameservers", []) or []]
        ns = "\n".join(f"  • <code>{utils.escape_html(n.lower())}</code>" for n in ns_list) or "  —"

        await utils.answer(
            message,
            self.strings("domain_card").format(
                emoji=emoji,
                domain=utils.escape_html(data.get("ldhName", arg).lower()),
                e_reg="🏢", registrar=utils.escape_html(registrar),
                e_status="📊", status=utils.escape_html(statuses),
                e_date="📅",
                created=self._events(data, "registration"),
                expires=self._events(data, "expiration"),
                e_ns="🖧", ns=ns,
            ),
        )

    @loader.command(ru_doc="<ip> — гео и провайдер IP", alias="ipinfo")
    async def ipcmd(self, message):
        """<ip> — IP geo and ISP"""
        emoji = self.config["emoji_net"]
        arg = utils.get_args_raw(message).strip()
        arg = _CLEAN.sub("", arg).split("/")[0]
        if not arg:
            return await utils.answer(
                message, self.strings("no_arg").format(emoji=emoji, p=self.get_prefix())
            )
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            _, data = await self._get_json(IPAPI.format(ip=arg))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ip failed: %s", exc)
            return await utils.answer(msg, self.strings("fail").format(
                utils.escape_html(str(exc))))
        if not isinstance(data, dict) or data.get("status") != "success":
            return await utils.answer(message, self.strings("not_found").format(
                utils.escape_html(arg)))

        flags = []
        if data.get("hosting"):
            flags.append("🖥 хостинг/ЦОД")
        if data.get("proxy"):
            flags.append("🛡 прокси/VPN")
        if data.get("mobile"):
            flags.append("📱 мобильная сеть")
        flags_line = ("⚑ " + " · ".join(flags)) if flags else ""

        await utils.answer(
            message,
            self.strings("ip_card").format(
                emoji=emoji,
                ip=utils.escape_html(data.get("query", arg)),
                e_geo="📍",
                country=utils.escape_html(data.get("country", "—")),
                cc=utils.escape_html(data.get("countryCode", "—")),
                region=utils.escape_html(data.get("regionName", "—")),
                city=utils.escape_html(data.get("city", "—")),
                e_isp="🌐", isp=utils.escape_html(data.get("isp", "—")),
                e_org="🏢", org=utils.escape_html(data.get("org", "—")),
                e_as="🔗", asn=utils.escape_html(data.get("as", "—")),
                e_rev="↩️", reverse=utils.escape_html(data.get("reverse", "") or "—"),
                e_tz="🕒", timezone=utils.escape_html(data.get("timezone", "—")),
                flags=flags_line,
            ),
        )
