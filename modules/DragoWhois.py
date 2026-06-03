__version__ = (1, 3, 2)

# meta developer: @dragomodules
# meta category: Сеть и сайты
# scope: heroku_only
# requires: aiohttp pillow
# changelog: цветные иконки на строках (Icons8) + фавикон/флаг в .netcard

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoWhois — инфо по домену и IP (whois, гео, провайдер).     ║
# ║  Текстом или картинкой-карточкой. Без API-ключей.             ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import re

import aiohttp

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = None

from .. import loader, utils

logger = logging.getLogger(__name__)

_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def _to_bot_emoji(text: str) -> str:
    """Телетоновский <emoji document_id=ID> → Bot API <tg-emoji emoji-id=ID> (для инлайна)."""
    return re.sub(
        r"<emoji document_id=(\d+)>(.*?)</emoji>",
        r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
        text,
        flags=re.DOTALL,
    )


async def _upload_image(data: bytes) -> str | None:
    """Заливает картинку на catbox→0x0, возвращает URL (для инлайн-формы)."""
    headers = {"User-Agent": "Mozilla/5.0 (DragoWhois)"}
    timeout = aiohttp.ClientTimeout(total=30)
    hosts = [
        ("https://catbox.moe/user/api.php", "fileToUpload", {"reqtype": "fileupload"}),
        ("https://0x0.st", "file", {}),
    ]
    for url, field, extra in hosts:
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                form = aiohttp.FormData()
                for k, v in extra.items():
                    form.add_field(k, v)
                form.add_field(field, data, filename="net.png")
                async with s.post(url, data=form) as r:
                    body = (await r.text()).strip()
                    if body.startswith("http"):
                        return body
        except Exception as e:  # noqa: BLE001
            logger.warning("net image upload via %s failed: %s", url, e)
    return None

WHOIS = "https://who-dat.as93.net/{domain}"
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
                "<emoji document_id=5258256103178804244>🌐</emoji>",
                "Эмодзи заголовка. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Отправлять ответы через инлайн-бота (от бота, а не аккаунта).",
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

    async def _get_json(self, url: str):
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {"User-Agent": "DragoWhois", "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(url) as r:
                return r.status, await r.json(content_type=None)

    # ── рендер карточки-картинки ────────────────────────────────
    def _font(self, name: str, size: int):
        try:
            return ImageFont.truetype(_FONT_DIR + name, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    async def _fetch_bytes(self, url: str) -> bytes | None:
        """Качает картинку-иконку (фавикон/флаг) из интернета."""
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {"User-Agent": "Mozilla/5.0 (DragoWhois)"}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.read()
                        if len(data) > 200:
                            return data
        except Exception as e:  # noqa: BLE001
            logger.debug("icon fetch failed %s: %s", url, e)
        return None

    async def _icon(self, name: str) -> bytes | None:
        """Цветная PNG-иконка Icons8 (с кешем в памяти)."""
        cache = getattr(self, "_icon_cache", None)
        if cache is None:
            cache = self._icon_cache = {}
        if name in cache:
            return cache[name]
        data = await self._fetch_bytes(f"https://img.icons8.com/fluency/48/{name}.png")
        cache[name] = data
        return data

    async def _favicon(self, domain: str) -> bytes | None:
        """Фавикон сайта: DuckDuckGo → Google (что вернётся первым)."""
        for url in (
            f"https://icons.duckduckgo.com/ip3/{domain}.ico",
            f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        ):
            data = await self._fetch_bytes(url)
            if data:
                return data
        return None

    def _render_card(self, kind: str, title: str, subtitle: str, rows: list,
                     logo: bytes = None, icons: dict = None) -> io.BytesIO:
        """kind: 'domain'|'ip'. rows: (icon_name, label, value). icons: {name: png}."""
        icons = icons or {}
        f_title = self._font("DejaVuSans-Bold.ttf", 34)
        f_sub = self._font("DejaVuSans.ttf", 18)
        f_key = self._font("DejaVuSans-Bold.ttf", 20)
        f_val = self._font("DejaVuSans.ttf", 20)

        pad = 40
        row_h = 46
        W = 900
        head_h = 96  # высота шапки с логотипом
        H = pad + head_h + 14 + len(rows) * row_h + pad

        img = Image.new("RGB", (W, H), (18, 20, 30))
        d = ImageDraw.Draw(img)
        if kind == "ip":
            top, bot, accent = (20, 24, 40), (34, 28, 52), (120, 170, 255)
        else:
            top, bot, accent = (18, 26, 28), (26, 40, 38), (120, 220, 170)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))

        muted = (140, 148, 178)
        white = (228, 232, 248)
        key_col = (170, 178, 210)

        # логотип из интернета (фавикон сайта / флаг страны) в шапке слева
        text_x = pad
        if logo:
            try:
                ic = Image.open(io.BytesIO(logo)).convert("RGBA")
                box = head_h - 8
                ic.thumbnail((box, box), Image.LANCZOS)
                iy = pad + (head_h - ic.height) // 2
                img.paste(ic, (pad, iy), ic)
                text_x = pad + box + 22
            except Exception as e:  # noqa: BLE001
                logger.debug("logo paste failed: %s", e)

        d.text((text_x, pad + 14), title, font=f_title, fill=accent)
        if subtitle:
            d.text((text_x, pad + 56), subtitle, font=f_sub, fill=muted)

        y = pad + head_h + 14
        d.line([(pad, y - 10), (W - pad, y - 10)], fill=(60, 66, 92), width=2)
        ic_sz = 28
        for icon_name, label, value in rows:
            # цветная иконка из интернета (или акцентный маркер, если не загрузилась)
            png = icons.get(icon_name)
            if png:
                try:
                    ic = Image.open(io.BytesIO(png)).convert("RGBA")
                    ic.thumbnail((ic_sz, ic_sz), Image.LANCZOS)
                    img.paste(ic, (pad, y + (28 - ic.height) // 2 + 2), ic)
                except Exception:  # noqa: BLE001
                    d.rounded_rectangle([pad, y + 6, pad + 8, y + 22], 3, fill=accent)
            else:
                d.rounded_rectangle([pad, y + 6, pad + 8, y + 22], 3, fill=accent)
            d.text((pad + ic_sz + 14, y), label, font=f_key, fill=key_col)
            val = str(value)
            if len(val) > 56:
                val = val[:55] + "…"
            d.text((pad + 300, y), val, font=f_val, fill=white)
            y += row_h
            d.line([(pad, y - 10), (W - pad, y - 10)], fill=(40, 44, 64), width=1)

        buf = io.BytesIO()
        buf.name = "dragonet.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    async def _send_card(self, message, img, caption: str):
        if self._inline_on:
            url = await _upload_image(img.getvalue())
            if url:
                try:
                    return await self.inline.form(
                        message=message, text=_to_bot_emoji(caption), photo=url
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inline card failed, fallback: %s", exc)
        img.seek(0)
        await utils.answer(message=message, response=caption, file=img)

    @loader.command(ru_doc="<домен> — whois домена", alias="domain")
    async def whoiscmd(self, message):
        """<domain> — domain whois"""
        emoji = self.config["emoji_net"]
        arg = utils.get_args_raw(message).strip().lower()
        arg = _CLEAN.sub("", arg).split("/")[0]
        if not arg:
            return await self._reply(
                message, self.strings("no_arg").format(emoji=emoji, p=self.get_prefix())
            )
        await self._status(message, self.strings("loading").format(emoji=emoji))
        try:
            status, data = await self._get_json(WHOIS.format(domain=arg))
            if status >= 400 or not isinstance(data, dict) or not data.get("isRegistered"):
                return await self._reply(message, self.strings("not_found").format(
                    utils.escape_html(arg)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("whois failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(
                utils.escape_html(str(exc))))

        registrar = (data.get("registrar") or {}).get("name") or "—"
        statuses = ", ".join(data.get("status", []) or []) or "—"
        dates = data.get("dates") or {}
        created = (dates.get("created") or "—")[:10]
        expires = (dates.get("expires") or "—")[:10]
        ns_list = [n.get("name", "") for n in data.get("nameservers", []) or []]
        ns = "\n".join(f"  • <code>{utils.escape_html(n.lower())}</code>" for n in ns_list) or "  —"

        await self._reply(
            message,
            self.strings("domain_card").format(
                emoji=emoji,
                domain=utils.escape_html(data.get("domain", arg).lower()),
                e_reg="🏢", registrar=utils.escape_html(registrar),
                e_status="📊", status=utils.escape_html(statuses),
                e_date="📅",
                created=created,
                expires=expires,
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
            return await self._reply(
                message, self.strings("no_arg").format(emoji=emoji, p=self.get_prefix())
            )
        await self._status(message, self.strings("loading").format(emoji=emoji))
        try:
            _, data = await self._get_json(IPAPI.format(ip=arg))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ip failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(
                utils.escape_html(str(exc))))
        if not isinstance(data, dict) or data.get("status") != "success":
            return await self._reply(message, self.strings("not_found").format(
                utils.escape_html(arg)))

        flags = []
        if data.get("hosting"):
            flags.append("🖥 хостинг/ЦОД")
        if data.get("proxy"):
            flags.append("🛡 прокси/VPN")
        if data.get("mobile"):
            flags.append("📱 мобильная сеть")
        flags_line = ("⚑ " + " · ".join(flags)) if flags else ""

        await self._reply(
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

    @loader.command(ru_doc="<домен|ip> — инфо картинкой", alias="netimg")
    async def netcardcmd(self, message):
        """<domain|ip> — domain/IP info as an image card"""
        emoji = self.config["emoji_net"]
        if Image is None:
            return await self._reply(message, "🚫 <b>Pillow не установлен.</b>")
        arg = utils.get_args_raw(message).strip()
        arg = _CLEAN.sub("", arg).split("/")[0]
        if not arg:
            return await self._reply(
                message, self.strings("no_arg").format(emoji=emoji, p=self.get_prefix())
            )
        await self._status(message, self.strings("loading").format(emoji=emoji))

        try:
            if _IP_RE.match(arg):
                _, data = await self._get_json(IPAPI.format(ip=arg))
                if not isinstance(data, dict) or data.get("status") != "success":
                    return await self._reply(message, self.strings("not_found").format(
                        utils.escape_html(arg)))
                flags = []
                if data.get("hosting"):
                    flags.append("хостинг/ЦОД")
                if data.get("proxy"):
                    flags.append("прокси/VPN")
                if data.get("mobile"):
                    flags.append("моб. сеть")
                rows = [
                    ("worldwide-location", "Страна", f"{data.get('country','—')} ({data.get('countryCode','—')})"),
                    ("map-marker", "Регион", f"{data.get('regionName','—')}, {data.get('city','—')}"),
                    ("internet", "Провайдер", data.get("isp", "—")),
                    ("company", "Организация", data.get("org", "—")),
                    ("domain", "AS", data.get("as", "—")),
                    ("server", "PTR", data.get("reverse") or "—"),
                    ("calendar", "Таймзона", data.get("timezone", "—")),
                    ("info", "Метки", " · ".join(flags) or "—"),
                ]
                cc = (data.get("countryCode") or "").lower()
                logo = await self._fetch_bytes(f"https://flagcdn.com/w160/{cc}.png") if cc else None
                icons = await self._collect_icons(rows)
                img = self._render_card("ip", data.get("query", arg), "IP-адрес", rows, logo, icons)
                caption = f"{emoji} <b>IP</b> <code>{utils.escape_html(data.get('query', arg))}</code>"
            else:
                arg = arg.lower()
                status, data = await self._get_json(WHOIS.format(domain=arg))
                if status >= 400 or not isinstance(data, dict) or not data.get("isRegistered"):
                    return await self._reply(message, self.strings("not_found").format(
                        utils.escape_html(arg)))
                dates = data.get("dates") or {}
                ns_list = [n.get("name", "") for n in data.get("nameservers", []) or []]
                rows = [
                    ("company", "Регистратор", (data.get("registrar") or {}).get("name") or "—"),
                    ("id-verified", "Статус", ", ".join(data.get("status", []) or []) or "—"),
                    ("calendar", "Создан", (dates.get("created") or "—")[:10]),
                    ("expired", "Истекает", (dates.get("expires") or "—")[:10]),
                    ("certificate", "DNSSEC", "да" if (data.get("dnssec") or {}).get("signed") else "нет"),
                    ("server", "NS", ", ".join(n.lower() for n in ns_list) or "—"),
                ]
                dom = data.get("domain", arg).lower()
                logo = await self._favicon(dom)
                icons = await self._collect_icons(rows)
                img = self._render_card("domain", dom, "Домен", rows, logo, icons)
                caption = f"{emoji} <b>Домен</b> <code>{utils.escape_html(dom)}</code>"
        except Exception as exc:  # noqa: BLE001
            logger.exception("netcard failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(
                utils.escape_html(str(exc))))

        await self._send_card(message, img, caption)

    async def _collect_icons(self, rows: list) -> dict:
        """Предзагружает PNG-иконки для всех строк карточки (с кешем)."""
        icons = {}
        for icon_name, *_ in rows:
            if icon_name not in icons:
                icons[icon_name] = await self._icon(icon_name)
        return icons
