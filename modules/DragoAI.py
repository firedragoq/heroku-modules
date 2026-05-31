__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: heroku_only
# requires: aiohttp

# ╔══════════════════════════════════════════════════════════════╗
# ║  DragoAI — чат с ИИ через OpenRouter (нужен бесплатный ключ).  ║
# ╚══════════════════════════════════════════════════════════════╝

import logging

import aiohttp

from .. import loader, utils

logger = logging.getLogger(__name__)

API = "https://openrouter.ai/api/v1/chat/completions"


@loader.tds
class DragoAIMod(loader.Module):
    """🤖 Чат с ИИ через OpenRouter (нужен бесплатный ключ)."""

    strings = {
        "name": "DragoAI",
        "no_key": (
            "🔑 <b>Нет API-ключа OpenRouter.</b>\n\n"
            "1. Получи бесплатный ключ на <code>openrouter.ai/keys</code>\n"
            "2. <code>{p}cfg DragoAI</code> → впиши его в <b>api_key</b>.\n"
            "Есть бесплатные модели (см. <code>model</code> в конфиге)."
        ),
        "no_prompt": (
            "🚫 <b>Задай вопрос.</b> Пример: <code>{p}ai как дела?</code> "
            "(или ответом на сообщение)."
        ),
        "thinking": "{emoji} <b>Думаю…</b>",
        "answer": "{emoji} <b>DragoAI</b>\n\n{text}",
        "fail": "🚫 <b>Ошибка ИИ:</b> <code>{}</code>",
        "cleared": "🧹 <b>Контекст диалога очищен.</b>",
    }

    strings_ru = {
        "_cls_doc": "🤖 Чат с ИИ через OpenRouter (нужен бесплатный ключ).",
        "aicmd_doc": "<запрос> — спросить ИИ",
        "airesetcmd_doc": "очистить контекст диалога",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "api_key",
                "",
                "API-ключ OpenRouter (openrouter.ai/keys).",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "model",
                "deepseek/deepseek-chat-v3-0324:free",
                "Модель OpenRouter (есть бесплатные с суффиксом :free).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "system_prompt",
                "Ты — полезный ассистент. Отвечай кратко, по делу, на языке вопроса.",
                "Системный промпт (характер ассистента).",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "context_size",
                6,
                "Сколько последних сообщений помнить (0 — без памяти).",
                validator=loader.validators.Integer(minimum=0, maximum=30),
            ),
            loader.ConfigValue(
                "emoji_ai",
                "🤖",
                "Эмодзи ИИ. Можно премиум (шлётся от аккаунта).",
                validator=loader.validators.String(),
            ),
        )

    def _history(self) -> list:
        return self.get("history", [])

    async def _ask(self, prompt: str) -> str:
        history = self._history()
        messages = [{"role": "system", "content": self.config["system_prompt"]}]
        messages += history
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/dragomodules",
            "X-Title": "DragoAI",
        }
        payload = {"model": self.config["model"], "messages": messages}
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(API, headers=headers, json=payload) as resp:
                data = await resp.json(content_type=None)
        if resp.status >= 400 or "choices" not in data:
            err = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
            raise RuntimeError(err or f"HTTP {resp.status}: {str(data)[:200]}")
        answer = data["choices"][0]["message"]["content"].strip()

        # сохраняем контекст
        size = int(self.config["context_size"])
        if size:
            history = history + [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ]
            self.set("history", history[-size * 2:])
        return answer

    @loader.command(ru_doc="<запрос> — спросить ИИ", alias="gpt")
    async def aicmd(self, message):
        """<prompt> — ask the AI"""
        if not self.config["api_key"]:
            return await utils.answer(
                message, self.strings("no_key").format(p=self.get_prefix())
            )
        prompt = utils.get_args_raw(message).strip()
        reply = await message.get_reply_message()
        if reply and reply.raw_text:
            quoted = reply.raw_text.strip()
            prompt = f"{prompt}\n\n{quoted}" if prompt else quoted
        if not prompt:
            return await utils.answer(
                message, self.strings("no_prompt").format(p=self.get_prefix())
            )

        emoji = self.config["emoji_ai"]
        msg = await utils.answer(message, self.strings("thinking").format(emoji=emoji))
        try:
            answer = await self._ask(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai failed: %s", exc)
            return await utils.answer(
                msg, self.strings("fail").format(utils.escape_html(str(exc)))
            )
        await utils.answer(
            msg,
            self.strings("answer").format(emoji=emoji, text=utils.escape_html(answer)),
        )

    @loader.command(ru_doc="очистить контекст диалога", alias="airs")
    async def airesetcmd(self, message):
        """Clear the conversation context"""
        self.set("history", [])
        await utils.answer(message, self.strings("cleared"))
