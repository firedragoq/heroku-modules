__version__ = (1, 6, 1)

# meta developer: @dragomodules
# meta category: Сеть и сайты
# scope: heroku_only
# requires: aiohttp pillow
# changelog: спарклайн в .price аккуратнее — сглаживание, точки мин/макс/текущей, базовая линия

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoCrypto — курсы крипты, конвертация и биржевой график.    ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging
import re
from datetime import datetime

import aiohttp

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = None

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


async def _upload_image(data: bytes) -> str | None:
    """Заливает картинку на catbox→0x0, возвращает URL (для инлайн-формы)."""
    headers = {"User-Agent": "Mozilla/5.0 (DragoCrypto)"}
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
                form.add_field(field, data, filename="crypto.png")
                async with s.post(url, data=form) as r:
                    body = (await r.text()).strip()
                    if body.startswith("http"):
                        return body
        except Exception as e:  # noqa: BLE001
            logger.warning("crypto image upload via %s failed: %s", url, e)
    return None

_FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

CG = "https://api.coingecko.com/api/v3"
FIAT = "https://open.er-api.com/v6/latest/{base}"

# частые тикеры → id CoinGecko (чтобы не дёргать поиск на популярных)
_KNOWN = {
    "btc": "bitcoin", "eth": "ethereum", "usdt": "tether", "bnb": "binancecoin",
    "sol": "solana", "xrp": "ripple", "usdc": "usd-coin", "ada": "cardano",
    "doge": "dogecoin", "trx": "tron", "ton": "the-open-network", "dot": "polkadot",
    "matic": "matic-network", "ltc": "litecoin", "shib": "shiba-inu",
    "avax": "avalanche-2", "link": "chainlink", "xmr": "monero", "near": "near",
}

# распространённые фиат-коды (для распознавания .conv)
_FIAT_CODES = {
    "usd", "eur", "rub", "uah", "kzt", "byn", "gbp", "jpy", "cny", "try",
    "pln", "czk", "chf", "cad", "aud", "inr", "brl", "amd", "gel", "azn",
}


@loader.tds
class DragoCryptoMod(loader.Module):
    """💰 Курсы криптовалют и конвертация валют (без API-ключей)."""

    strings = {
        "name": "DragoCrypto",
        "no_args_price": (
            "🚫 <b>Укажи монету.</b> Пример: <code>{p}price btc</code> "
            "или <code>{p}price eth sol ton</code>."
        ),
        "no_args_conv": (
            "🚫 <b>Формат:</b> <code>{p}conv 100 usd rub</code> "
            "или <code>{p}conv 0.5 btc usd</code>."
        ),
        "loading": "{emoji} <b>Запрашиваю курс…</b>",
        "not_found": "🚫 <b>Не найдено:</b> <code>{}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "price_head": "{emoji} <b>Курсы криптовалют</b>",
        "price_row": (
            "{e} <b>{name}</b> <code>{sym}</code>\n"
            "    {cur1}  ·  {chg}"
        ),
        "conv_result": "{emoji} <b>{amount} {src}</b> = <b>{result} {dst}</b>",
        "no_args_chart": (
            "🚫 <b>Укажи монету.</b> Пример: <code>{p}chart btc</code> "
            "или <code>{p}chart eth 30</code> (дней)."
        ),
        "chart_caption": (
            "{emoji} <b>{name}</b> <code>{sym}</code> · {cur}\n"
            "{arrow} <b>{chg}</b> за {days}д  ·  ↑ {hi}  ↓ {lo}"
        ),
    }

    strings_ru = {
        "_cls_doc": "💰 Курсы криптовалют, конвертация и биржевой график (без API-ключей).",
        "pricecmd_doc": "<монета…> — курс криптовалюты",
        "convcmd_doc": "<сумма> <из> <в> — конвертация валют/крипты",
        "chartcmd_doc": "<монета> [дней] — биржевой график",
        "no_args_price": (
            "🚫 <b>Укажи монету.</b> Пример: <code>{p}price btc</code> "
            "или <code>{p}price eth sol ton</code>."
        ),
        "no_args_conv": (
            "🚫 <b>Формат:</b> <code>{p}conv 100 usd rub</code> "
            "или <code>{p}conv 0.5 btc usd</code>."
        ),
        "loading": "{emoji} <b>Запрашиваю курс…</b>",
        "not_found": "🚫 <b>Не найдено:</b> <code>{}</code>",
        "fail": "🚫 <b>Ошибка:</b> <code>{}</code>",
        "price_head": "{emoji} <b>Курсы криптовалют</b>",
        "price_row": (
            "{e} <b>{name}</b> <code>{sym}</code>\n"
            "    {cur1}  ·  {chg}"
        ),
        "conv_result": "{emoji} <b>{amount} {src}</b> = <b>{result} {dst}</b>",
        "no_args_chart": (
            "🚫 <b>Укажи монету.</b> Пример: <code>{p}chart btc</code> "
            "или <code>{p}chart eth 30</code> (дней)."
        ),
        "chart_caption": (
            "{emoji} <b>{name}</b> <code>{sym}</code> · {cur}\n"
            "{arrow} <b>{chg}</b> за {days}д  ·  ↑ {hi}  ↓ {lo}"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "vs_currency",
                "rub",
                "Основная валюта котировок (rub, usd, eur…).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_crypto",
                '<emoji document_id=5258076470466617642>💳</emoji>',
                "Эмодзи заголовка. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_coin",
                '<emoji document_id=5258504365173415947>💯</emoji>',
                "Эмодзи перед каждой монетой в списке.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_up",
                '<emoji document_id=5260464635491949616>🚀</emoji>',
                "Эмодзи роста за 24ч.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_down",
                '<emoji document_id=5260319946633681748>🛑</emoji>',
                "Эмодзи падения за 24ч.",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "as_image",
                False,
                "Отправлять курсы (.price) и конвертацию (.conv) картинкой-карточкой.",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "use_inline",
                False,
                "Картинку-карточку слать через инлайн-бота (нужно as_image=True).",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "chart_days",
                7,
                "Период графика .chart по умолчанию (дней).",
                validator=loader.validators.Integer(minimum=1, maximum=365),
            ),
        )

    async def client_ready(self, client, db):
        self._client = client
        self._db = db
        # одноразовая миграция старых сохранённых дефолтов на новые
        if not self.get("_migrated_v14", False):
            if (self.config["vs_currency"] or "").lower() == "usd":
                self.config["vs_currency"] = "rub"
            migrate = {
                "emoji_crypto": ("💰", "<emoji document_id=5258076470466617642>💳</emoji>"),
                "emoji_up": ("📈", "<emoji document_id=5260464635491949616>🚀</emoji>"),
                "emoji_down": ("📉", "<emoji document_id=5260319946633681748>🛑</emoji>"),
            }
            for key, (old, new) in migrate.items():
                if self.config[key] == old:
                    self.config[key] = new
            self.set("_migrated_v14", True)

    # ── HTTP ────────────────────────────────────────────────────
    async def _get_json(self, url: str, params: dict | None = None):
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {"User-Agent": "DragoCrypto", "Accept": "application/json"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
            async with s.get(url, params=params) as r:
                r.raise_for_status()
                return await r.json(content_type=None)

    async def _resolve_id(self, ticker: str) -> str | None:
        """Тикер/имя → CoinGecko id."""
        t = ticker.lower().strip()
        if t in _KNOWN:
            return _KNOWN[t]
        try:
            data = await self._get_json(f"{CG}/search", {"query": t})
        except Exception:  # noqa: BLE001
            return None
        coins = data.get("coins") or []
        if not coins:
            return None
        # точное совпадение по символу — приоритетно
        for c in coins:
            if c.get("symbol", "").lower() == t:
                return c.get("id")
        return coins[0].get("id")

    @staticmethod
    def _fmt(num: float) -> str:
        if num >= 1:
            return f"{num:,.2f}".replace(",", " ")
        return f"{num:.6f}".rstrip("0").rstrip(".")

    @property
    def _inline_on(self) -> bool:
        return bool(self.config["use_inline"]) and getattr(self, "inline", None) is not None

    async def _reply(self, message, text: str):
        """Текстовый ответ: инлайн-бот (use_inline) или utils.answer."""
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

    async def _send_card(self, message, img, caption: str):
        """Шлёт картинку-карточку: через инлайн-бота (use_inline) или от аккаунта."""
        if self.config["use_inline"] and getattr(self, "inline", None):
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

    # ── рендер картинки ─────────────────────────────────────────
    def _font(self, name: str, size: int):
        try:
            return ImageFont.truetype(_FONT_DIR + name, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    @staticmethod
    def _smooth(values, window=5):
        """Скользящее среднее для сглаживания спарклайна."""
        n = len(values)
        if n < 3 or window < 2:
            return values
        half = window // 2
        out = []
        for i in range(n):
            a, b = max(0, i - half), min(n, i + half + 1)
            out.append(sum(values[a:b]) / (b - a))
        return out

    def _sparkline(self, d, prices, x, y, w, h, color):
        """Аккуратный мини-график: сглаживание, заливка, точки мин/макс и текущей."""
        pts = [p for p in (prices or []) if isinstance(p, (int, float))]
        if len(pts) < 2 or w < 10:
            return
        sm = self._smooth(pts)
        lo, hi = min(sm), max(sm)
        rng = (hi - lo) or 1
        n = len(sm)

        def cx(i):
            return x + w * i / (n - 1)

        def cy(v):
            return y + h - (v - lo) / rng * h

        coords = [(cx(i), cy(v)) for i, v in enumerate(sm)]
        # мягкая заливка под линией
        base = (16, 18, 27)
        fill = tuple(int(color[i] * 0.28 + base[i] * 0.72) for i in range(3))
        d.polygon(coords + [(coords[-1][0], y + h), (coords[0][0], y + h)], fill=fill)
        # пунктирная нулевая линия (старт периода) — видно рост/падение
        y_start = cy(sm[0])
        for sx in range(int(x), int(x + w), 8):
            d.line([(sx, y_start), (sx + 4, y_start)], fill=(70, 74, 96), width=1)
        d.line(coords, fill=color, width=2, joint="curve")
        # точки макс/мин и текущей цены
        hi_i, lo_i = sm.index(hi), sm.index(lo)
        d.ellipse([cx(hi_i) - 3, cy(hi) - 3, cx(hi_i) + 3, cy(hi) + 3],
                  fill=(118, 201, 124))
        d.ellipse([cx(lo_i) - 3, cy(lo) - 3, cx(lo_i) + 3, cy(lo) + 3],
                  fill=(240, 110, 120))
        d.ellipse([cx(n - 1) - 3, cy(sm[-1]) - 3, cx(n - 1) + 3, cy(sm[-1]) + 3],
                  fill=(240, 185, 66))

    def _render_image(self, coins: list, cur_sign: str) -> io.BytesIO:
        f_title = self._font("DejaVuSans-Bold.ttf", 34)
        f_sub = self._font("DejaVuSans.ttf", 18)
        f_name = self._font("DejaVuSans-Bold.ttf", 26)
        f_sym = self._font("DejaVuSansMono.ttf", 18)
        f_price = self._font("DejaVuSansMono-Bold.ttf", 26)
        f_chg = self._font("DejaVuSans-Bold.ttf", 20)

        pad = 36
        row_h = 78
        W = 820
        H = pad + 60 + 16 + len(coins) * row_h + pad

        img = Image.new("RGB", (W, H), (20, 22, 33))
        d = ImageDraw.Draw(img)
        top, bot = (24, 26, 38), (40, 33, 58)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))

        accent = (240, 185, 66)
        muted = (130, 138, 170)
        white = (228, 232, 248)
        up_col = (118, 201, 124)
        down_col = (240, 110, 120)

        d.text((pad, pad), "DragoCrypto", font=f_title, fill=accent)
        d.text((pad, pad + 40), f"Курсы · {cur_sign}", font=f_sub, fill=muted)

        y = pad + 60 + 16
        d.line([(pad, y - 10), (W - pad, y - 10)], fill=(60, 64, 88), width=2)
        for c in coins:
            price = c.get("current_price") or 0
            chg = c.get("price_change_percentage_24h")
            name = c.get("name", "?")
            sym = (c.get("symbol", "") or "").upper()

            d.text((pad, y + 6), name, font=f_name, fill=white)
            d.text((pad, y + 40), sym, font=f_sym, fill=muted)

            price_txt = f"{self._fmt(price)} {cur_sign}"
            pw = d.textlength(price_txt, font=f_price)
            d.text((W - pad - pw, y + 6), price_txt, font=f_price, fill=white)

            if chg is None:
                chg_txt, col = "—", muted
            else:
                arrow = "▲" if chg >= 0 else "▼"
                chg_txt = f"{arrow} {chg:+.2f}%"
                col = up_col if chg >= 0 else down_col
            cw = d.textlength(chg_txt, font=f_chg)
            d.text((W - pad - cw, y + 42), chg_txt, font=f_chg, fill=col)

            # 7-дневный мини-график между названием и ценой
            spark = ((c.get("sparkline_in_7d") or {}).get("price")) or []
            self._sparkline(
                d, spark, x=pad + 230, y=y + 12, w=W - pad - pad - 230 - 200, h=44,
                color=up_col if (chg or 0) >= 0 else down_col,
            )

            y += row_h
            d.line([(pad, y - 14), (W - pad, y - 14)], fill=(44, 48, 68), width=1)

        buf = io.BytesIO()
        buf.name = "dragocrypto.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    def _render_chart(self, name, sym, cur_sign, points, days) -> io.BytesIO:
        """Биржевой график: оси цены и дат, сетка, линия с заливкой, мин/макс.

        points — список [ts_ms, price]. Возвращает PNG.
        """
        f_title = self._font("DejaVuSans-Bold.ttf", 30)
        f_price = self._font("DejaVuSans-Bold.ttf", 26)
        f_axis = self._font("DejaVuSans.ttf", 16)
        f_small = self._font("DejaVuSans.ttf", 15)

        W, H = 1000, 560
        pad_l, pad_r, pad_t, pad_b = 30, 110, 110, 60  # отступы под оси/заголовок
        gx0, gy0 = pad_l, pad_t
        gx1, gy1 = W - pad_r, H - pad_b
        gw, gh = gx1 - gx0, gy1 - gy0

        prices = [p[1] for p in points]
        times = [p[0] / 1000 for p in points]
        lo, hi = min(prices), max(prices)
        first, last = prices[0], prices[-1]
        rng = (hi - lo) or (hi or 1)
        up = last >= first
        line_col = (118, 201, 124) if up else (240, 110, 120)
        fill_col = (40, 70, 50) if up else (70, 42, 48)

        img = Image.new("RGB", (W, H), (16, 18, 27))
        d = ImageDraw.Draw(img)
        top, bot = (22, 24, 36), (30, 26, 44)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))

        accent = (240, 185, 66)
        grid = (44, 48, 70)
        muted = (140, 148, 178)
        white = (228, 232, 248)

        # заголовок
        d.text((pad_l, 28), f"{name} ({sym})", font=f_title, fill=white)
        cur_txt = f"{self._fmt(last)} {cur_sign}"
        d.text((pad_l, 66), cur_txt, font=f_price, fill=accent)
        chg_pct = (last - first) / first * 100 if first else 0
        chg_txt = f"{'▲' if up else '▼'} {chg_pct:+.2f}%  ·  {days}д"
        d.text((pad_l + d.textlength(cur_txt, font=f_price) + 24, 70),
               chg_txt, font=f_axis, fill=line_col)

        def py(price):  # цена → координата Y
            return gy1 - (price - lo) / rng * gh

        def px(i):  # индекс точки → координата X
            return gx0 + gw * i / (len(prices) - 1)

        # горизонтальная сетка + подписи цен справа (5 линий)
        for k in range(5):
            val = lo + rng * k / 4
            yy = py(val)
            d.line([(gx0, yy), (gx1, yy)], fill=grid, width=1)
            d.text((gx1 + 8, yy - 8), self._fmt(val), font=f_small, fill=muted)

        # вертикальная сетка + даты снизу (5 меток)
        for k in range(5):
            i = round((len(prices) - 1) * k / 4)
            xx = px(i)
            d.line([(xx, gy0), (xx, gy1)], fill=grid, width=1)
            fmt = "%d.%m" if days > 2 else "%H:%M"
            label = datetime.fromtimestamp(times[i]).strftime(fmt)
            tw = d.textlength(label, font=f_small)
            d.text((xx - tw / 2, gy1 + 10), label, font=f_small, fill=muted)

        # заливка под линией + сама линия
        coords = [(px(i), py(p)) for i, p in enumerate(prices)]
        d.polygon(coords + [(gx1, gy1), (gx0, gy1)], fill=fill_col)
        d.line(coords, fill=line_col, width=3, joint="curve")

        # маркеры макс/мин
        hi_i, lo_i = prices.index(hi), prices.index(lo)
        for idx, val, col, dy in ((hi_i, hi, (118, 201, 124), -22), (lo_i, lo, (240, 110, 120), 8)):
            x, y = px(idx), py(val)
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col)
            lab = self._fmt(val)
            lw = d.textlength(lab, font=f_small)
            d.text((min(max(x - lw / 2, gx0), gx1 - lw), y + dy), lab, font=f_small, fill=col)

        # точка текущей цены
        d.ellipse([gx1 - 5, py(last) - 5, gx1 + 5, py(last) + 5], fill=accent)

        buf = io.BytesIO()
        buf.name = "dragochart.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    def _render_conv_image(self, amount: float, src: str, result: float, dst: str) -> io.BytesIO:
        f_title = self._font("DejaVuSans-Bold.ttf", 30)
        f_big = self._font("DejaVuSans-Bold.ttf", 46)
        f_mid = self._font("DejaVuSans.ttf", 28)
        f_arrow = self._font("DejaVuSans.ttf", 40)

        W, H = 820, 360
        img = Image.new("RGB", (W, H), (20, 22, 33))
        d = ImageDraw.Draw(img)
        top, bot = (24, 26, 38), (40, 33, 58)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))

        accent = (240, 185, 66)
        white = (228, 232, 248)
        muted = (130, 138, 170)

        d.text((36, 30), "DragoCrypto · конвертация", font=f_title, fill=accent)
        d.line([(36, 80), (W - 36, 80)], fill=(60, 64, 88), width=2)

        def center(text, font, y, fill):
            w = d.textlength(text, font=font)
            d.text(((W - w) / 2, y), text, font=font, fill=fill)

        center(f"{self._fmt(amount)} {src.upper()}", f_big, 120, white)
        center("↓", f_arrow, 190, accent)
        center(f"{self._fmt(result)} {dst.upper()}", f_big, 250, accent)

        buf = io.BytesIO()
        buf.name = "dragoconv.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    # ── .price ──────────────────────────────────────────────────
    @loader.command(ru_doc="<монета…> — курс криптовалюты", alias="p")
    async def pricecmd(self, message):
        """<coin…> — crypto price"""
        args = utils.get_args_raw(message).strip()
        if not args:
            return await self._reply(
                message, self.strings("no_args_price").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_crypto"]
        await self._status(message, self.strings("loading").format(emoji=emoji))

        vs = self.config["vs_currency"].lower()
        tickers = args.split()[:10]
        ids = {}
        for t in tickers:
            cid = await self._resolve_id(t)
            if cid:
                ids[cid] = t
        if not ids:
            return await self._reply(message, self.strings("not_found").format(
                utils.escape_html(args)))

        try:
            data = await self._get_json(
                f"{CG}/coins/markets",
                {
                    "vs_currency": vs,
                    "ids": ",".join(ids),
                    "price_change_percentage": "24h",
                    "sparkline": "true",  # 7-дневный график для карточки
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("price failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(
                utils.escape_html(str(exc))))

        cur_sign = vs.upper()

        # картинкой, если включено и PIL доступен
        if self.config["as_image"] and Image is not None:
            try:
                img = self._render_image(data, cur_sign)
                return await self._send_card(
                    message, img, self.strings("price_head").format(emoji=emoji)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("image render failed, fallback to text: %s", exc)

        rows = [self.strings("price_head").format(emoji=emoji), ""]
        for c in data:
            price = c.get("current_price") or 0
            chg = c.get("price_change_percentage_24h")
            if chg is None:
                chg_str = "—"
            else:
                arrow = self.config["emoji_up"] if chg >= 0 else self.config["emoji_down"]
                chg_str = f"{arrow} {chg:+.2f}%"
            rows.append(self.strings("price_row").format(
                e=self.config["emoji_coin"],
                name=utils.escape_html(c.get("name", "?")),
                sym=utils.escape_html((c.get("symbol", "") or "").upper()),
                cur1=f"{self._fmt(price)} {cur_sign}",
                chg=chg_str,
            ))
        await self._reply(message, "\n".join(rows))

    # ── .conv ───────────────────────────────────────────────────
    @loader.command(ru_doc="<сумма> <из> <в> — конвертация", alias="conv")
    async def convertcmd(self, message):
        """<amount> <from> <to> — convert currencies/crypto"""
        parts = utils.get_args_raw(message).split()
        if len(parts) < 3:
            return await self._reply(
                message, self.strings("no_args_conv").format(p=self.get_prefix())
            )
        try:
            amount = float(parts[0].replace(",", "."))
        except ValueError:
            return await self._reply(
                message, self.strings("no_args_conv").format(p=self.get_prefix())
            )
        src, dst = parts[1].lower(), parts[2].lower()

        emoji = self.config["emoji_crypto"]
        await self._status(message, self.strings("loading").format(emoji=emoji))
        try:
            result = await self._convert(amount, src, dst)
        except Exception as exc:  # noqa: BLE001
            logger.exception("convert failed: %s", exc)
            return await self._reply(message, self.strings("fail").format(
                utils.escape_html(str(exc))))
        if result is None:
            return await self._reply(message, self.strings("not_found").format(
                f"{utils.escape_html(src)}→{utils.escape_html(dst)}"))

        # картинкой, если включено и PIL доступен
        if self.config["as_image"] and Image is not None:
            try:
                img = self._render_conv_image(amount, src, result, dst)
                return await self._send_card(
                    message, img,
                    self.strings("conv_result").format(
                        emoji=emoji,
                        amount=self._fmt(amount),
                        src=src.upper(),
                        result=self._fmt(result),
                        dst=dst.upper(),
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("conv image render failed, fallback to text: %s", exc)

        await self._reply(
            message,
            self.strings("conv_result").format(
                emoji=emoji,
                amount=self._fmt(amount),
                src=src.upper(),
                result=self._fmt(result),
                dst=dst.upper(),
            ),
        )

    # ── .chart ──────────────────────────────────────────────────
    @loader.command(ru_doc="<монета> [дней] — биржевой график", alias="graph")
    async def chartcmd(self, message):
        """<coin> [days] — exchange-style price chart"""
        if Image is None:
            return await self._reply(
                message, "🚫 <b>Pillow не установлен.</b>"
            )
        parts = utils.get_args_raw(message).split()
        if not parts:
            return await self._reply(
                message, self.strings("no_args_chart").format(p=self.get_prefix())
            )
        ticker = parts[0]
        days = int(self.config["chart_days"])
        if len(parts) > 1 and parts[1].isdigit():
            days = max(1, min(365, int(parts[1])))

        emoji = self.config["emoji_crypto"]
        await self._status(message, self.strings("loading").format(emoji=emoji))

        cid = await self._resolve_id(ticker)
        if not cid:
            return await self._reply(
                message, self.strings("not_found").format(utils.escape_html(ticker))
            )
        vs = self.config["vs_currency"].lower()
        try:
            data = await self._get_json(
                f"{CG}/coins/{cid}/market_chart",
                {"vs_currency": vs, "days": days},
            )
            meta = await self._get_json(
                f"{CG}/coins/markets",
                {"vs_currency": vs, "ids": cid},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("chart failed: %s", exc)
            return await self._reply(
                message, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        points = data.get("prices") or []
        if len(points) < 2:
            return await self._reply(
                message, self.strings("not_found").format(utils.escape_html(ticker))
            )

        m = meta[0] if meta else {}
        name = m.get("name", ticker.upper())
        sym = (m.get("symbol", ticker) or "").upper()
        cur_sign = vs.upper()
        prices = [p[1] for p in points]
        first, last = prices[0], prices[-1]
        chg = (last - first) / first * 100 if first else 0

        try:
            img = self._render_chart(name, sym, cur_sign, points, days)
        except Exception as exc:  # noqa: BLE001
            logger.exception("chart render failed: %s", exc)
            return await self._reply(
                message, self.strings("fail").format(utils.escape_html(str(exc)))
            )

        caption = self.strings("chart_caption").format(
            emoji=emoji,
            name=utils.escape_html(name),
            sym=utils.escape_html(sym),
            cur=f"{self._fmt(last)} {cur_sign}",
            arrow=self.config["emoji_up"] if chg >= 0 else self.config["emoji_down"],
            chg=f"{chg:+.2f}%",
            days=days,
            hi=f"{self._fmt(max(prices))} {cur_sign}",
            lo=f"{self._fmt(min(prices))} {cur_sign}",
        )
        await self._send_card(message, img, caption)

    async def _convert(self, amount: float, src: str, dst: str) -> float | None:
        src_fiat = src in _FIAT_CODES
        dst_fiat = dst in _FIAT_CODES

        if src_fiat and dst_fiat:
            data = await self._get_json(FIAT.format(base=src.upper()))
            rate = (data.get("rates") or {}).get(dst.upper())
            return amount * rate if rate else None

        # хотя бы одна сторона — крипта: считаем через общую vs-валюту (usd)
        async def crypto_usd(ticker: str) -> float | None:
            cid = await self._resolve_id(ticker)
            if not cid:
                return None
            d = await self._get_json(
                f"{CG}/simple/price", {"ids": cid, "vs_currencies": "usd"}
            )
            return (d.get(cid) or {}).get("usd")

        async def fiat_per_usd(code: str) -> float | None:
            if code == "usd":
                return 1.0
            d = await self._get_json(FIAT.format(base="USD"))
            return (d.get("rates") or {}).get(code.upper())

        # стоимость 1 src в usd
        if src_fiat:
            r = await fiat_per_usd(src)
            src_in_usd = 1 / r if r else None
        else:
            src_in_usd = await crypto_usd(src)
        if not src_in_usd:
            return None

        # стоимость 1 dst в usd
        if dst_fiat:
            r = await fiat_per_usd(dst)
            dst_in_usd = 1 / r if r else None
        else:
            dst_in_usd = await crypto_usd(dst)
        if not dst_in_usd:
            return None

        return amount * src_in_usd / dst_in_usd
