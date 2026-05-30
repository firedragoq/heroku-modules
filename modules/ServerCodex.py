__version__ = (1, 0, 0)

# meta developer: @dragomodules
# scope: terminal_access_true

import asyncio
import html
import json
import re
import time

import aiohttp
import google.generativeai as genai
import psutil

from .. import loader, utils

SYSTEM_PROMPT = (
    "Ты — Codex, системный администратор. Отвечай кратко и понятно. "
    "Не используй жирный текст (**). "
    "НИКОГДА не указывай пароли, токены, API ключи или конфиденциальные данные."
)

DANGEROUS_PATTERNS = [
    r"\brm\s+(-[^\s]*r|-[^\s]*f|--recursive)\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bsystemctl\s+(stop|disable|mask)\s",
    r"\bkill\s+-9\s+1\b",
    r"\bchmod\s+(-R\s+)?777\s+/\s",
    r"\biptables\s+-F\b",
    r">\s*/dev/sd",
    r"\b(wget|curl)\b.*\|\s*(ba)?sh",
    r"\bpkill\s+-9\b",
    r"\brmdir\s+/",
]


@loader.tds
class ServerCodexMod(loader.Module):
    """🪐 Server Codex: AI System Core"""

    strings = {
        "name": "ServerCodex",
        "info": "🪐 **Server Codex (v10.0.0)**\n🫶 **Разработчик: @firedragoq**",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "GEMINI_KEY", "", "🔵 API ключ Google Gemini",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "OPENROUTER_KEY", "", "🟠 API ключ OpenRouter",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "AI_PROVIDER", "gemini", "🤖 Провайдер ИИ",
                validator=loader.validators.Choice(["gemini", "openrouter", "openclaw"]),
            ),
            loader.ConfigValue("DEFAULT_MODEL", "gemini-2.0-flash", "Модель Gemini"),
            loader.ConfigValue("OPENROUTER_MODEL", "meta-llama/llama-4-maverick", "Модель OpenRouter"),
            loader.ConfigValue("OPENCLAW_MODEL", "openclaw/main", "Модель/агент OpenClaw"),
            loader.ConfigValue(
                "OPENCLAW_TOKEN", "", "🔑 Токен OpenClaw Gateway",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue("OPENCLAW_BOT", "", "🤖 Username Telegram-бота OpenClaw"),
            loader.ConfigValue(
                "OPENCLAW_TIMEOUT", 30, "⏳ Таймаут ответа OpenClaw (сек)",
                validator=loader.validators.Integer(minimum=5, maximum=120),
            ),
            loader.ConfigValue(
                "API_TIMEOUT", 15, "⏱️ Таймаут API (сек)",
                validator=loader.validators.Integer(minimum=5, maximum=300),
            ),
            loader.ConfigValue("SAFE_MODE", True, "🔒 Безопасный режим"),
            loader.ConfigValue("LOG_COMMANDS", True, "📋 Логировать команды"),
            loader.ConfigValue(
                "SUDO_PASSWORD", "", "🔐 Пароль sudo",
                validator=loader.validators.Hidden(),
            ),
        )
        self.pending_confirmations = {}
        self.command_log = []
        self.request_count = 0
        self._session = None
        self._provider = None
        self.model = None
        self.openrouter_key = None
        self.openrouter_model = None
        self.openclaw_model = None

    async def client_ready(self, client, db):
        self._client = client
        self.db = db
        self._init_ai()

    async def on_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _init_ai(self):
        provider = self.config["AI_PROVIDER"].lower()
        self._provider = provider
        self.model = None
        self.openrouter_key = None
        self.openrouter_model = None
        self.openclaw_model = None

        if provider == "openclaw":
            self.openclaw_model = self.config["OPENCLAW_MODEL"]
            self.model = "openclaw"
        elif provider == "openrouter":
            key = self.config["OPENROUTER_KEY"]
            if not key:
                return
            self.openrouter_key = key
            self.openrouter_model = self.config["OPENROUTER_MODEL"]
            self.model = "openrouter"
        else:
            key = self.config["GEMINI_KEY"]
            if not key:
                return
            try:
                genai.configure(api_key=key)
                m_name = self.config["DEFAULT_MODEL"]
                if not m_name.startswith("models/"):
                    m_name = f"models/{m_name}"
                self.model = genai.GenerativeModel(
                    model_name=m_name,
                    system_instruction=SYSTEM_PROMPT,
                )
            except Exception:
                self.model = None

    def _ensure_provider(self):
        if self.config["AI_PROVIDER"].lower() != self._provider:
            self._init_ai()

    def _is_dangerous(self, cmd):
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True
        return False

    def _log_command(self, cmd, status, output=""):
        if not self.config["LOG_COMMANDS"]:
            return
        entry = {
            "timestamp": time.time(),
            "command": cmd,
            "status": status,
            "output_preview": output[:100] if output else "",
        }
        self.command_log.append(entry)
        try:
            logs = self.db.get("ServerCodex", "command_logs", [])
            logs.append(entry)
            self.db.set("ServerCodex", "command_logs", logs[-100:])
        except Exception:
            pass

    async def _ask_ai(self, prompt, fast=False):
        self._ensure_provider()
        if not self.model:
            self._init_ai()
        if not self.model:
            return "❌ Настройте API ключ для выбранного провайдера"

        if self._provider == "openclaw":
            return await self._ask_openclaw(prompt)
        if self._provider == "openrouter":
            return await self._ask_openrouter(prompt, fast=fast)
        return await self._ask_gemini(prompt, fast=fast)

    async def _ask_gemini(self, prompt, fast=False):
        try:
            if not self.model or isinstance(self.model, str):
                return "❌ Модель Gemini не инициализирована. Проверьте API ключ."

            gen_config = {"temperature": 0, "max_output_tokens": 300} if fast else None

            res = await asyncio.wait_for(
                asyncio.to_thread(
                    self.model.generate_content,
                    prompt,
                    generation_config=gen_config,
                ),
                timeout=float(self.config["API_TIMEOUT"]),
            )
            return res.text
        except asyncio.TimeoutError:
            return "❌ Тайм-аут Gemini API"
        except Exception as e:
            return f"❌ Gemini: {e}"

    async def _ask_openrouter(self, prompt, fast=False):
        try:
            session = self._get_session()
            headers = {
                "Authorization": f"Bearer {self.openrouter_key}",
                "HTTP-Referer": "https://github.com",
                "X-Title": "ServerCodex",
            }
            payload = {
                "model": self.openrouter_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0 if fast else 0.7,
                "max_tokens": 300 if fast else 2000,
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=float(self.config["API_TIMEOUT"])),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                error_data = await resp.text()
                return f"❌ OpenRouter ({resp.status}): {error_data[:200]}"
        except asyncio.TimeoutError:
            return "❌ Тайм-аут OpenRouter API"
        except Exception as e:
            return f"❌ OpenRouter: {e}"

    async def _ask_openclaw(self, prompt):
        bot_username = self.config.get("OPENCLAW_BOT", "").strip()
        if not bot_username:
            return "❌ Укажите OPENCLAW_BOT в настройках модуля"

        timeout = int(self.config.get("OPENCLAW_TIMEOUT", 30))
        edit_settle = 3

        try:
            sent = await self._client.send_message(bot_username, prompt)
            sent_id = sent.id
            reply_msg = None
            last_text = None
            last_edit_time = None
            deadline = time.time() + timeout

            while time.time() < deadline:
                await asyncio.sleep(1)
                messages = await self._client.get_messages(bot_username, limit=10)
                for msg in messages:
                    if msg.id > sent_id and not msg.out:
                        reply_msg = msg
                        break
                if reply_msg is None:
                    continue

                fresh = await self._client.get_messages(bot_username, ids=reply_msg.id)
                current_text = fresh.text if fresh else ""

                if current_text != last_text:
                    last_text = current_text
                    last_edit_time = time.time()
                elif last_edit_time and (time.time() - last_edit_time) >= edit_settle:
                    return last_text or "❌ Бот ответил пустым сообщением"

            return last_text or "❌ OpenClaw бот не ответил за отведённое время"
        except Exception as e:
            return f"❌ OpenClaw [{type(e).__name__}]: {e}"

    def _get_system_resources(self):
        try:
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            return (
                f"CPU: {cpu}%\n"
                f"Память: {mem.percent}% ({mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB)\n"
                f"Диск: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)\n"
                f"Процессы: {len(psutil.pids())}"
            )
        except Exception:
            return "Не удалось получить данные о ресурсах"

    async def _run_bash(self, cmd):
        cmd = cmd.strip().replace("`", "")

        if "<<" in cmd and "EOF" in cmd:
            cmd = cmd.replace("'EOF'", "EOF")
        elif not any(kw in cmd for kw in ["<<", "cat >", "echo >"]):
            cmd = cmd.split("\n")[0]

        if self._is_dangerous(cmd):
            self._log_command(cmd, "BLOCKED_DANGEROUS")
            return f"⚠️ ОПАСНАЯ КОМАНДА ЗАБЛОКИРОВАНА: {cmd}"

        timeout = float(self.config["API_TIMEOUT"])
        if "logs" in cmd or "tail" in cmd:
            timeout *= 2

        try:
            if "sudo" in cmd and self.config["SUDO_PASSWORD"]:
                password = self.config["SUDO_PASSWORD"]
                cmd = f"echo '{password}' | sudo -S {cmd.replace('sudo ', '', 1)}"

            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            out = stdout.decode() if stdout else ""
            err = stderr.decode() if stderr else ""
            if not out and err:
                out = err

            out = re.sub(r"\x1b\[[0-9;]*[mK]", "", out.strip())
            if len(out) > 2000:
                out = out[:2000].rsplit("\n", 1)[0] + "\n[... обрезано]"

            self._log_command(cmd, "SUCCESS", out[:500])
            return out
        except asyncio.TimeoutError:
            msg = f"❌ Команда выполнялась слишком долго (>{timeout}с)"
            self._log_command(cmd, "TIMEOUT", msg)
            return msg
        except Exception as e:
            msg = f"❌ {type(e).__name__}: {e}"
            self._log_command(cmd, "ERROR", msg)
            return msg

    def _model_info(self):
        p = self.config["AI_PROVIDER"].lower()
        if p == "openrouter":
            return f"🟠 {self.config['OPENROUTER_MODEL']}"
        if p == "openclaw":
            return f"🟣 {self.config['OPENCLAW_MODEL']}"
        return f"🔵 {self.config['DEFAULT_MODEL']}"

    @loader.command(alias="sc")
    async def sccmd(self, message):
        """<запрос> — Умный ответ от AI (анализ, команды, вопросы)"""
        query = utils.get_args_raw(message)
        if not query:
            return await utils.answer(message, "ℹ️ Введите запрос.")

        self.request_count += 1
        await utils.answer(message, "🧠 `Думаю...`")

        reply = await message.get_reply_message()
        code_context = ""
        if reply and (reply.text or reply.document):
            if reply.text:
                code_context = f"Код для анализа:\n```\n{reply.text}\n```\n\n"
            elif reply.document:
                try:
                    data = await reply.download_media(bytes)
                    code_context = f"Файл:\n```\n{data.decode('utf-8', errors='ignore')}\n```\n\n"
                except Exception:
                    pass

        header = f"🧠 [{self.request_count}/∞]\n💬 {query}\n{self._model_info()}"

        if code_context:
            ai_res = await self._ask_ai(f"{code_context}Запрос: {query}")
            if not ai_res or ai_res.startswith("❌"):
                return await utils.answer(message, ai_res or "❌ Нет ответа")
            res = ai_res.replace("**", "").replace("__", "").strip()
            return await utils.answer(
                message,
                f"{header}\n\n<blockquote>{html.escape(res)}</blockquote>",
                parse_mode="html",
            )

        route_prompt = f"""Запрос: {query}

Определи, нужна ли bash-команда на Linux-сервере.

Если ДА — ответь строго:
CMD: <одна bash-команда>

Если НЕТ (вопрос, объяснение, совет) — ответь строго:
ANS: <твой ответ>

Для CMD: только одна команда, без объяснений. Для файлов: cat << 'EOF' > filename. Для ресурсов: CMD: INFO"""

        raw = await self._ask_ai(route_prompt, fast=True)
        if not raw or raw.startswith("❌"):
            return await utils.answer(message, raw or "❌ Нет ответа")

        raw = raw.strip()

        if raw.upper().startswith("ANS:"):
            res = raw[4:].strip().replace("**", "").replace("__", "")
            return await utils.answer(
                message,
                f"{header}\n\n<blockquote>{html.escape(res)}</blockquote>",
                parse_mode="html",
            )

        cmd = raw
        if raw.upper().startswith("CMD:"):
            cmd = raw[4:].strip()
        cmd = cmd.replace("`", "").strip()

        if not any(kw in cmd for kw in ["<<", "cat >", "echo >"]):
            cmd = cmd.split("\n")[0]

        if self._is_dangerous(cmd):
            confirm_id = f"cmd_{self.request_count}"
            self.pending_confirmations[confirm_id] = {
                "cmd": cmd,
                "query": query,
                "request_count": self.request_count,
            }
            buttons = [
                [
                    {"text": "✅ Выполнить", "callback": self._confirm_cmd, "args": (confirm_id,)},
                    {"text": "❌ Отменить", "callback": self._cancel_cmd, "args": (confirm_id,)},
                ]
            ]
            return await utils.answer(
                message, f"⚠️ ОПАСНАЯ КОМАНДА:\n\n`{cmd}`", reply_markup=buttons,
            )

        sys_out = ""
        if "INFO" not in cmd.upper() and len(cmd) > 2:
            sys_out = await self._run_bash(cmd)

        if not sys_out or "ошибка" in sys_out.lower():
            if any(w in query.lower() for w in ["ресурс", "память", "cpu", "диск", "процесс"]):
                sys_out = self._get_system_resources()

        final_prompt = f"""Запрос: {query}
Команда: {cmd}
Результат:
{sys_out}

Ответь кратко и по сути. Проблемы — первыми. Без форматирования."""

        ai_res = await self._ask_ai(final_prompt)
        res = ai_res.replace("**", "").replace("__", "").replace("`", "").strip()
        res = res.replace("<blockquote>", "").replace("</blockquote>", "")

        await utils.answer(
            message,
            f"{header}\n\n<blockquote>{html.escape(res)}</blockquote>",
            parse_mode="html",
        )

    @loader.command(alias="scping")
    async def scpingcmd(self, message):
        """Проверить статус модуля"""
        await utils.answer(message, self.strings["info"])

    @loader.command(alias="sclogs")
    async def sclogscmd(self, message):
        """Показать логи команд"""
        if not self.command_log:
            return await utils.answer(message, "📋 Логи пусты")
        text = "📋 Последние команды:\n"
        for i, log in enumerate(self.command_log[-10:], 1):
            icon = "✅" if log["status"] == "SUCCESS" else "⏱" if log["status"] == "TIMEOUT" else "❌"
            short = log["command"][:40].replace("\n", " ")
            text += f"\n{i}. {icon} {short}{'...' if len(log['command']) > 40 else ''}"
        await utils.answer(message, text)

    @loader.command(alias="scsafe")
    async def scsafecmd(self, message):
        """Переключить безопасный режим"""
        self.config["SAFE_MODE"] = not self.config["SAFE_MODE"]
        s = "✅ ВКЛЮЧЕН" if self.config["SAFE_MODE"] else "❌ ОТКЛЮЧЕН"
        await utils.answer(message, f"🔒 Безопасный режим: {s}")

    @loader.command(alias="scyes")
    async def scyescmd(self, message):
        """Подтвердить опасную команду"""
        if not self.pending_confirmations:
            return await utils.answer(message, "❌ Нет ожидающих команд")
        confirm_id = list(self.pending_confirmations.keys())[-1]
        data = self.pending_confirmations.pop(confirm_id)
        cmd = data["cmd"]

        await utils.answer(message, f"⚡ Выполняю: `{cmd}`")
        sys_out = await self._run_bash(cmd)

        ai_res = await self._ask_ai(
            f"Выполнена команда: {cmd}\nРезультат:\n{sys_out}\nОбъясни кратко."
        )
        res = ai_res.replace("**", "").replace("__", "").replace("`", "").strip()
        await utils.answer(
            message,
            f"<blockquote>{html.escape(res)}</blockquote>",
            parse_mode="html",
        )

    @loader.command(alias="scno")
    async def scnocmd(self, message):
        """Отменить опасную команду"""
        if not self.pending_confirmations:
            return await utils.answer(message, "❌ Нет ожидающих команд")
        confirm_id = list(self.pending_confirmations.keys())[-1]
        data = self.pending_confirmations.pop(confirm_id)
        await utils.answer(message, f"❌ Отменено: `{data['cmd']}`")

    async def _confirm_cmd(self, call, confirm_id):
        if confirm_id not in self.pending_confirmations:
            return await call.answer("❌ Команда уже обработана", alert=True)
        data = self.pending_confirmations.pop(confirm_id)
        cmd, query, rc = data["cmd"], data["query"], data["request_count"]

        await call.edit("⚡ Выполняю...")
        sys_out = await self._run_bash(cmd)

        ai_res = await self._ask_ai(
            f"Запрос: {query}\nКоманда: {cmd}\nРезультат:\n{sys_out}\n"
            "Ответь кратко, без форматирования."
        )
        res = ai_res.replace("**", "").replace("__", "").replace("`", "").strip()
        res = res.replace("<blockquote>", "").replace("</blockquote>", "")

        h = f"🧠 [{rc}/∞]\n💬 {query}\n\n✅ ВЫПОЛНЕНО"
        await call.edit(
            f"{h}\n\n<blockquote>{html.escape(res)}</blockquote>",
            reply_markup=None,
        )

    async def _cancel_cmd(self, call, confirm_id):
        if confirm_id not in self.pending_confirmations:
            return await call.answer("❌ Команда уже обработана", alert=True)
        data = self.pending_confirmations.pop(confirm_id)
        await call.edit(f"❌ Отменено:\n\n`{data['cmd']}`", reply_markup=None)
