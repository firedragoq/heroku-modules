__version__ = (1, 4, 0)

# meta developer: @dragomodules
# meta category: Сеть и сайты
# scope: heroku_only
# requires: aiohttp pillow
# changelog: 7-дневный график в карточке .price; миграция старого конфига (rub + премиум-эмодзи)

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoCrypto — курсы крипты и конвертация валют (без ключей).  ║
# ║  Опционально — красивая карточка-картинка с курсами.           ║
# ╚══════════════════════════════════════════════════════════════╝

import io
import logging

import aiohttp

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    Image = None

from .. import loader, utils

logger = logging.getLogger(__name__)

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
    }

    strings_ru = {
        "_cls_doc": "💰 Курсы криптовалют и конвертация валют (без API-ключей).",
        "pricecmd_doc": "<монета…> — курс криптовалюты",
        "convcmd_doc": "<сумма> <из> <в> — конвертация валют/крипты",
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

    # ── рендер картинки ─────────────────────────────────────────
    def _font(self, name: str, size: int):
        try:
            return ImageFont.truetype(_FONT_DIR + name, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    @staticmethod
    def _sparkline(d, prices, x, y, w, h, color):
        """Рисует мини-график цены (7д) с лёгкой заливкой под линией."""
        pts = [p for p in (prices or []) if isinstance(p, (int, float))]
        if len(pts) < 2 or w < 10:
            return
        lo, hi = min(pts), max(pts)
        rng = (hi - lo) or 1
        n = len(pts)
        coords = [
            (x + w * i / (n - 1), y + h - (p - lo) / rng * h)
            for i, p in enumerate(pts)
        ]
        # полупрозрачная заливка под линией
        fill = tuple(int(c * 0.35 + 30 * 0.65) for c in color)
        d.polygon(
            coords + [(coords[-1][0], y + h), (coords[0][0], y + h)], fill=fill
        )
        d.line(coords, fill=color, width=2, joint="curve")

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
            return await utils.answer(
                message, self.strings("no_args_price").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_crypto"]
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))

        vs = self.config["vs_currency"].lower()
        tickers = args.split()[:10]
        ids = {}
        for t in tickers:
            cid = await self._resolve_id(t)
            if cid:
                ids[cid] = t
        if not ids:
            return await utils.answer(message, self.strings("not_found").format(
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
            return await utils.answer(message, self.strings("fail").format(
                utils.escape_html(str(exc))))

        cur_sign = vs.upper()

        # картинкой, если включено и PIL доступен
        if self.config["as_image"] and Image is not None:
            try:
                img = self._render_image(data, cur_sign)
                return await utils.answer(
                    message=message,
                    response=self.strings("price_head").format(emoji=emoji),
                    file=img,
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
        await utils.answer(message, "\n".join(rows))

    # ── .conv ───────────────────────────────────────────────────
    @loader.command(ru_doc="<сумма> <из> <в> — конвертация", alias="conv")
    async def convertcmd(self, message):
        """<amount> <from> <to> — convert currencies/crypto"""
        parts = utils.get_args_raw(message).split()
        if len(parts) < 3:
            return await utils.answer(
                message, self.strings("no_args_conv").format(p=self.get_prefix())
            )
        try:
            amount = float(parts[0].replace(",", "."))
        except ValueError:
            return await utils.answer(
                message, self.strings("no_args_conv").format(p=self.get_prefix())
            )
        src, dst = parts[1].lower(), parts[2].lower()

        emoji = self.config["emoji_crypto"]
        msg = await utils.answer(message, self.strings("loading").format(emoji=emoji))
        try:
            result = await self._convert(amount, src, dst)
        except Exception as exc:  # noqa: BLE001
            logger.exception("convert failed: %s", exc)
            return await utils.answer(message, self.strings("fail").format(
                utils.escape_html(str(exc))))
        if result is None:
            return await utils.answer(message, self.strings("not_found").format(
                f"{utils.escape_html(src)}→{utils.escape_html(dst)}"))

        # картинкой, если включено и PIL доступен
        if self.config["as_image"] and Image is not None:
            try:
                img = self._render_conv_image(amount, src, result, dst)
                return await utils.answer(
                    message=message,
                    response=self.strings("conv_result").format(
                        emoji=emoji,
                        amount=self._fmt(amount),
                        src=src.upper(),
                        result=self._fmt(result),
                        dst=dst.upper(),
                    ),
                    file=img,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("conv image render failed, fallback to text: %s", exc)

        await utils.answer(
            message,
            self.strings("conv_result").format(
                emoji=emoji,
                amount=self._fmt(amount),
                src=src.upper(),
                result=self._fmt(result),
                dst=dst.upper(),
            ),
        )

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
