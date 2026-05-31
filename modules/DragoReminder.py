__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoReminder — напоминания: разовые и повторяющиеся.         ║
# ╚══════════════════════════════════════════════════════════════╝

import asyncio
import logging
import re
import time

from .. import loader, utils

logger = logging.getLogger(__name__)

# 1d 2h 30m 15s  /  90m  /  1h30m  — в любом порядке и слитно
_UNIT = {"d": 86400, "h": 3600, "m": 60, "s": 1, "д": 86400, "ч": 3600, "м": 60, "с": 1}
_TOKEN_RE = re.compile(r"(\d+)\s*([dhmsдчмс])", re.IGNORECASE)


def _parse_duration(text: str) -> int:
    """Возвращает длительность в секундах из строки вида '1h30m' / '90m'. 0 — не распознано."""
    total = 0
    matched = False
    for num, unit in _TOKEN_RE.findall(text):
        total += int(num) * _UNIT[unit.lower()]
        matched = True
    return total if matched else 0


def _fmt(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s and not d and not h:
        parts.append(f"{s}с")
    return " ".join(parts) or "0с"


@loader.tds
class DragoReminderMod(loader.Module):
    """🔔 Напоминания: разовые и повторяющиеся."""

    strings = {
        "name": "DragoReminder",
        "usage": (
            "{emoji} <b>DragoReminder</b>\n\n"
            "<code>{p}remind 10m купить кофе</code> — напомнить через 10 минут\n"
            "<code>{p}remind 1h30m текст</code> — через 1ч 30м\n"
            "<code>{p}remind every 1h текст</code> — каждый час\n"
            "Ответом на сообщение — напомню о нём.\n\n"
            "<code>{p}reminds</code> — список · <code>{p}rmremind id</code> — удалить"
        ),
        "bad_time": (
            "🚫 <b>Не понял время.</b> Примеры: <code>10m</code>, "
            "<code>1h30m</code>, <code>2d</code>, <code>45s</code>."
        ),
        "no_text": "🚫 <b>Добавь текст напоминания.</b>",
        "set": (
            "{emoji} <b>Напомню через {when}</b>"
            "{rep}\n📝 <i>{text}</i>\n🆔 <code>{id}</code>"
        ),
        "repeat_suffix": " <b>(каждые {iv})</b>",
        "fire": "{emoji} <b>Напоминание!</b>\n\n📝 {text}",
        "fire_rep": "{emoji} <b>Напоминание</b> <i>(каждые {iv})</i>\n\n📝 {text}",
        "empty": "📭 <b>Активных напоминаний нет.</b>",
        "list_head": "{emoji} <b>Напоминания ({n}):</b>",
        "list_item": "🆔 <code>{id}</code> · через <b>{when}</b>{rep}\n📝 <i>{text}</i>",
        "removed": "🗑 <b>Напоминание</b> <code>{id}</code> <b>удалено.</b>",
        "not_found": "🚫 <b>Напоминание</b> <code>{id}</code> <b>не найдено.</b>",
        "cleared": "🧹 <b>Удалено напоминаний: {n}.</b>",
    }

    strings_ru = {
        "_cls_doc": "🔔 Напоминания: разовые и повторяющиеся.",
        "remindcmd_doc": "<время> <текст> — поставить напоминание (10m, 1h30m, every 1h)",
        "remindscmd_doc": "список активных напоминаний",
        "rmremindcmd_doc": "<id|all> — удалить напоминание",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "emoji_bell",
                "<emoji document_id=5458603043203327669>🔔</emoji>",
                "Эмодзи напоминания. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "emoji_wait",
                "<emoji document_id=5386367538735104399>⌛️</emoji>",
                "Эмодзи ожидания (при установке/в списке).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "ping_self",
                True,
                "Упоминать тебя (ping) в тексте напоминания.",
                validator=loader.validators.Boolean(),
            ),
        )

    async def client_ready(self, client, db):
        self._db = db

    # ── хранилище ───────────────────────────────────────────────
    def _all(self) -> list:
        return self.get("reminders", [])

    def _save(self, items: list):
        self.set("reminders", items)

    def _next_id(self) -> int:
        nid = int(self.get("next_id", 1))
        self.set("next_id", nid + 1)
        return nid

    # ── команды ─────────────────────────────────────────────────
    @loader.command(ru_doc="<время> <текст> — напоминание (10m, 1h30m, every 1h)")
    async def remindcmd(self, message):
        """<time> <text> — set a reminder (10m, 1h30m, every 1h)"""
        args = utils.get_args_raw(message).strip()
        if not args:
            return await utils.answer(
                message, self.strings("usage").format(
                    emoji=self.config["emoji_bell"], p=self.get_prefix()
                )
            )

        repeat = 0
        m = re.match(r"(?:every|каждые?|каждый)\s+(\S+)\s*(.*)", args, re.IGNORECASE)
        if m:
            repeat = _parse_duration(m.group(1))
            if not repeat:
                return await utils.answer(message, self.strings("bad_time"))
            delay = repeat
            text = m.group(2).strip()
        else:
            parts = args.split(maxsplit=1)
            delay = _parse_duration(parts[0])
            if not delay:
                return await utils.answer(message, self.strings("bad_time"))
            text = parts[1].strip() if len(parts) > 1 else ""

        reply = await message.get_reply_message()
        reply_to = None
        if reply:
            reply_to = reply.id
            if not text:
                text = (reply.raw_text or "").strip()[:200] or "(сообщение выше)"
        if not text:
            return await utils.answer(message, self.strings("no_text"))

        rid = self._next_id()
        items = self._all()
        items.append({
            "id": rid,
            "chat": utils.get_chat_id(message),
            "text": text,
            "fire_at": time.time() + delay,
            "repeat": repeat,
            "reply_to": reply_to,
        })
        self._save(items)

        rep = ""
        if repeat:
            rep = self.strings("repeat_suffix").format(iv=_fmt(repeat))
        await utils.answer(
            message,
            self.strings("set").format(
                emoji=self.config["emoji_wait"],
                when=_fmt(delay),
                rep=rep,
                text=utils.escape_html(text),
                id=rid,
            ),
        )

    @loader.command(ru_doc="список активных напоминаний", alias="reminders")
    async def remindscmd(self, message):
        """List active reminders"""
        items = sorted(self._all(), key=lambda r: r["fire_at"])
        if not items:
            return await utils.answer(message, self.strings("empty"))
        now = time.time()
        lines = [self.strings("list_head").format(
            emoji=self.config["emoji_bell"], n=len(items)
        ), ""]
        for r in items:
            rep = ""
            if r.get("repeat"):
                rep = self.strings("repeat_suffix").format(iv=_fmt(r["repeat"]))
            lines.append(self.strings("list_item").format(
                id=r["id"],
                when=_fmt(r["fire_at"] - now),
                rep=rep,
                text=utils.escape_html(r["text"][:120]),
            ))
        await utils.answer(message, "\n".join(lines))

    @loader.command(ru_doc="<id|all> — удалить напоминание", alias="unremind")
    async def rmremindcmd(self, message):
        """<id|all> — delete a reminder"""
        arg = utils.get_args_raw(message).strip().lower()
        items = self._all()
        if arg == "all":
            n = len(items)
            self._save([])
            return await utils.answer(message, self.strings("cleared").format(n=n))
        if not arg.isdigit():
            return await utils.answer(message, self.strings("not_found").format(id=arg or "?"))
        rid = int(arg)
        new = [r for r in items if r["id"] != rid]
        if len(new) == len(items):
            return await utils.answer(message, self.strings("not_found").format(id=rid))
        self._save(new)
        await utils.answer(message, self.strings("removed").format(id=rid))

    # ── фоновый цикл ────────────────────────────────────────────
    @loader.loop(interval=15, autostart=True)
    async def ticker(self):
        items = self._all()
        if not items:
            return
        now = time.time()
        due = [r for r in items if r["fire_at"] <= now]
        if not due:
            return

        rest = [r for r in items if r["fire_at"] > now]
        for r in due:
            await self._fire(r)
            if r.get("repeat"):
                r["fire_at"] = now + r["repeat"]
                rest.append(r)
        self._save(rest)

    async def _fire(self, r: dict):
        text = utils.escape_html(r["text"])
        if self.config["ping_self"]:
            try:
                me = await self._client.get_me()
                if getattr(me, "username", None):
                    text = f"@{me.username} {text}"
            except Exception:  # noqa: BLE001
                pass
        key = "fire_rep" if r.get("repeat") else "fire"
        body = self.strings(key).format(
            emoji=self.config["emoji_bell"],
            text=text,
            iv=_fmt(r.get("repeat", 0)),
        )
        try:
            await self._client.send_message(
                r["chat"], body, reply_to=r.get("reply_to")
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("reminder send failed, retry without reply: %s", exc)
            try:
                await self._client.send_message(r["chat"], body)
            except Exception as exc2:  # noqa: BLE001
                logger.warning("reminder %s lost: %s", r.get("id"), exc2)
