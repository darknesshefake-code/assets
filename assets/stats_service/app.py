"""
Сервис статистики переписки — API для сайта.

Что делает:
  • держит авторизованную сессию Telegram (Telethon) и считает сообщения
    только в одном чате (по умолчанию +380669543625);
  • хранит счётчики в SQLite и досчитывает новые сообщения инкрементально
    (по последнему id), поэтому после перезапуска ничего не теряется;
  • отдаёт готовые цифры сайту: GET /api/stats
  • умеет входить в Telegram ПРЯМО ЧЕРЕЗ БРАУЗЕР: /login — отсканировал QR
    телефоном (Настройки → Устройства → Подключить устройство) и готово,
    код подтверждения вводить не нужно.

Переменные окружения (задаются в Render → Environment):
  API_ID, API_HASH   — с https://my.telegram.org
  LOGIN_SECRET       — любое секретное слово: включает страницу входа /login?secret=...
  TG_SESSION         — StringSession ОБЫЧНОГО АККАУНТА (необязательно, если входил через /login).
                       ⚠️ сессия бота не подходит: Telegram запрещает ботам читать историю
  TARGET_PHONE       — чей чат считаем (по умолчанию +380669543625)
  TARGET_USERNAME    — необязательно: @username собеседницы вместо номера
  TARGET_NAME        — как называть собеседницу на сайте (необязательно)
  MY_NAME            — как называть себя (по умолчанию «Я»)
  TRIGGER_WORD       — слово в чате, на которое сервис отвечает цифрами (по умолчанию «инфо»)
  SYNC_INTERVAL      — как часто досчитывать, секунд (по умолчанию 60)
  ON_DEMAND_COOLDOWN — не чаще, чем раз в N секунд обновлять по запросу сайта
  ALLOWED_ORIGINS    — список источников через запятую или * (по умолчанию *)
  DB_PATH            — путь к файлу базы (по умолчанию stats.db рядом с кодом)
"""

import asyncio
import html as html_mod
import io
import logging
import os
import re
import secrets as pysecrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stats")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


API_ID = int(env("API_ID", "0") or 0)
API_HASH = env("API_HASH")
TG_SESSION = env("TG_SESSION")
LOGIN_SECRET = env("LOGIN_SECRET")
PUBLIC_URL = env("RENDER_EXTERNAL_URL") or env("PUBLIC_URL")
TARGET_PHONE = env("TARGET_PHONE", "+380669543625")
TARGET_NAME = env("TARGET_NAME") or None
MY_NAME = env("MY_NAME") or "Я"
SYNC_INTERVAL = int(env("SYNC_INTERVAL", "60") or 60)
ON_DEMAND_COOLDOWN = int(env("ON_DEMAND_COOLDOWN", "25") or 25)
DIALOG_SCAN_LIMIT = int(env("DIALOG_SCAN_LIMIT", "400") or 400)
TRIGGER_WORD = env("TRIGGER_WORD", "инфо")           # слово в чате, на которое отвечаем цифрами
TARGET_USERNAME = env("TARGET_USERNAME")             # необязательно: @username вместо номера
MAX_HISTORY = int(env("MAX_HISTORY", "0") or 0) or None      # 0 = вся история
DB_PATH = env("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.db"))
ALLOWED_ORIGINS = [o.strip() for o in env("ALLOWED_ORIGINS", "*").split(",") if o.strip()] or ["*"]

BOT_SESSION_HINT = (
    "Сессия принадлежит БОТУ. Telegram запрещает ботам читать историю чатов и список диалогов "
    "(GetDialogs / GetHistory). Войди в Telegram со своего аккаунта на странице входа: %s/login"
)


def login_hint() -> str:
    """Что написать, если вход в Telegram ещё не выполнен."""
    suffix = ("Открой %s/login?secret=<твой LOGIN_SECRET> и отсканируй QR-код телефоном "
              "(Telegram → Настройки → Устройства → Подключить устройство). "
              "Код подтверждения не нужен." % PUBLIC_URL) if PUBLIC_URL else \
             ("Открой страницу входа <адрес сервиса>/login?secret=<твой LOGIN_SECRET> "
              "и отсканируй QR-код телефоном.")
    if not LOGIN_SECRET:
        return ("Вход в Telegram не выполнен. Добавь в Render переменную LOGIN_SECRET "
                "(любое слово) — она включает страницу входа. После этого открой "
                "<адрес сервиса>/login?secret=это_слово и отсканируй QR-код телефоном.")
    return "Нужно подключить Telegram: %s" % suffix


def clean_session(raw: str) -> str:
    """Убирает кавычки, пробелы и переводы строк — частая причина «Not a valid string»."""
    s = (raw or "").strip()
    for ch in ('"', "'", "`"):
        s = s.strip(ch).strip()
    return s.replace("\n", "").replace("\r", "").replace(" ", "").replace("\t", "")


def session_problem(session: str) -> Optional[str]:
    """Проверяет строку сессии и объясняет, что не так. None — всё в порядке."""
    if not session:
        return None
    try:
        StringSession(session)          # принимает только корректный формат Telethon
        return None
    except Exception:
        pass

    hints = []
    try:
        import base64, struct
        data = base64.urlsafe_b64decode(session + "=" * (-len(session) % 4))
        if len(data) not in (275, 263):
            hints.append("длина %d байт не соответствует формату Telethon (нужно 275) — "
                         "похоже, строка сделана другим генератором или библиотекой" % len(data))
        if data and data[0] != 1:
            hints.append("первый байт версии %d вместо 1" % data[0])
    except Exception:
        hints.append("строка не декодируется — похоже, скопирована не полностью "
                     "или в ней лишние символы")

    if session[0] != "1":
        hints.append("Telethon-сессия всегда начинается с символа «1», а эта — с «%s»" % session[0])
    if len(session) < 300:
        hints.append("слишком короткая строка (%d символов, у Telethon-сессии ≈ 369)" % len(session))
    return "; ".join(hints) or "формат не распознан"


state: Dict[str, Any] = {
    "status": "starting",     # starting | ok | syncing | login | error
    "error": None,
    "entity": None,
    "title": None,
    "me": 0,
    "other": 0,
    "last_id": 0,
    "first_message_at": None,
    "last_message_at": None,
    "updated_ts": 0.0,
    "sync_seconds": None,
    "processed": 0,
    "is_bot": False,
    "handlers_added": False,
    "lock": asyncio.Lock(),
}

login_state: Dict[str, Any] = {
    "qr": None, "qr_url": None, "qr_version": 0,
    "qr_state": "idle",       # idle | waiting | password | done | error
    "qr_error": None, "qr_task": None, "session": None,
    "phone": None, "hash": None, "last_code_request": 0.0,
}


# ────────────────────────────── база ──────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chat_stats (
               chat_id           INTEGER PRIMARY KEY,
               title             TEXT,
               me                INTEGER DEFAULT 0,
               other             INTEGER DEFAULT 0,
               last_id           INTEGER DEFAULT 0,
               first_message_at  TEXT,
               last_message_at   TEXT,
               updated_ts        REAL
           )"""
    )
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def db_read() -> Optional[sqlite3.Row]:
    try:
        with db() as conn:
            return conn.execute("SELECT * FROM chat_stats ORDER BY updated_ts DESC LIMIT 1").fetchone()
    except Exception:
        log.exception("не смог прочитать базу")
        return None


def db_write(**fields: Any) -> None:
    with db() as conn:
        cur = conn.execute("SELECT chat_id FROM chat_stats LIMIT 1").fetchone()
        if cur is None:
            conn.execute(
                """INSERT INTO chat_stats (chat_id, title, me, other, last_id,
                                           first_message_at, last_message_at, updated_ts)
                   VALUES (:chat_id, :title, :me, :other, :last_id,
                           :first_message_at, :last_message_at, :updated_ts)""",
                fields,
            )
        else:
            conn.execute(
                """UPDATE chat_stats SET title = :title, me = :me, other = :other,
                       last_id = :last_id, first_message_at = :first_message_at,
                       last_message_at = :last_message_at, updated_ts = :updated_ts
                   WHERE chat_id = :chat_id""",
                fields,
            )


def db_set(key: str, value: str) -> None:
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def db_get(key: str) -> Optional[str]:
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None
    except Exception:
        return None


def load_from_db() -> bool:
    """Поднимает последние цифры из базы — чтобы сайт видел данные сразу после старта."""
    row = db_read()
    if row is None:
        return False
    state.update(
        me=int(row["me"] or 0),
        other=int(row["other"] or 0),
        last_id=int(row["last_id"] or 0),
        title=row["title"],
        first_message_at=row["first_message_at"],
        last_message_at=row["last_message_at"],
        updated_ts=float(row["updated_ts"] or 0),
    )
    log.info("поднял из базы: я=%s, собеседник=%s", state["me"], state["other"])
    return True


# ─────────────────────── клиент и поиск чата ───────────────────────

client: Optional[TelegramClient] = None


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def phone_matches(phone: Optional[str], target: str = TARGET_PHONE) -> bool:
    a, b = digits(phone or ""), digits(target)
    if not a or not b:
        return False
    n = min(len(a), len(b), 10)
    return a[-n:] == b[-n:]


async def resolve_entity(force: bool = False):
    """Находит собеседника: по username, затем по телефону, затем перебором диалогов."""
    global client
    if state["entity"] is not None and not force:
        return state["entity"]

    # 0) если задан username — пробуем сразу его
    if TARGET_USERNAME:
        try:
            entity = await client.get_entity(TARGET_USERNAME)
            state["entity"] = entity
            state["title"] = TARGET_NAME or getattr(entity, "first_name", None) or TARGET_USERNAME
            log.info("нашёл чат по username: %s", state["title"])
            return entity
        except Exception as exc:
            log.info("по username не нашлось (%s)", type(exc).__name__)

    # 1) пробуем напрямую по номеру телефона
    try:
        entity = await client.get_entity(TARGET_PHONE)
        state["entity"] = entity
        state["title"] = TARGET_NAME or getattr(entity, "first_name", None) or TARGET_PHONE
        log.info("нашёл чат напрямую: %s", state["title"])
        return entity
    except errors.BotMethodInvalidError:
        raise RuntimeError(BOT_SESSION_HINT % (PUBLIC_URL or ""))
    except Exception as exc:
        log.info("по номеру не нашлось (%s), перебираю диалоги…", type(exc).__name__)

    # 2) перебираем диалоги и сравниваем номер телефона
    try:
        async for dialog in client.iter_dialogs(limit=DIALOG_SCAN_LIMIT):
            ent = dialog.entity
            if getattr(ent, "bot", False):
                continue
            if phone_matches(getattr(ent, "phone", None)):
                state["entity"] = ent
                state["title"] = TARGET_NAME or getattr(ent, "first_name", None) or dialog.name or TARGET_PHONE
                log.info("нашёл чат среди диалогов: %s (id=%s)", state["title"], ent.id)
                return ent
    except errors.BotMethodInvalidError:
        raise RuntimeError(BOT_SESSION_HINT % (PUBLIC_URL or ""))

    raise RuntimeError(
        "Не нашёл диалог с %s. Проверь номер: чат должен существовать в аккаунте, "
        "номер — в международном формате." % TARGET_PHONE
    )


# ─────────────────────────── синхронизация ───────────────────────────

async def sync_once(force_full: bool = False) -> None:
    """Досчитывает сообщения в целевом чате (инкрементально, по min_id)."""
    if client is None:
        return
    async with state["lock"]:
        row = db_read()
        if row is None:
            force_full = True

        entity = await resolve_entity()
        chat_id = int(getattr(entity, "id", 0))
        title = state["title"] or TARGET_NAME or str(chat_id)

        min_id = 0 if force_full else int(row["last_id"] or 0)
        me = 0 if force_full else int(row["me"] or 0)
        other = 0 if force_full else int(row["other"] or 0)
        first_at = None if force_full else row["first_message_at"]
        last_at = None if force_full else row["last_message_at"]
        last_id = min_id
        processed = 0

        state["status"] = "syncing"
        state["processed"] = 0
        started = time.time()
        log.info("считаю чат «%s»: %s", title, "вся история" if force_full else "только новое")

        try:
            async for msg in client.iter_messages(entity, min_id=min_id, reverse=True, limit=MAX_HISTORY):
                last_id = max(last_id, msg.id)
                if msg.text is None and msg.media is None:
                    continue                                   # системное сообщение — не считаем
                if msg.out:
                    me += 1
                else:
                    other += 1

                processed += 1
                state["processed"] = processed
                if msg.date:
                    stamp = msg.date.astimezone(timezone.utc).isoformat()
                    if first_at is None or stamp < first_at:
                        first_at = stamp
                    if last_at is None or stamp > last_at:
                        last_at = stamp

                if processed % 500 == 0:
                    log.info("…обработано %s сообщений", processed)
                    await asyncio.sleep(0.05)
        except errors.FloodWaitError as exc:
            log.warning("Telegram просит подождать %s сек (FloodWait)", exc.seconds)
            state["status"] = "ok"
            raise

        db_write(
            chat_id=chat_id, title=title, me=me, other=other, last_id=last_id,
            first_message_at=first_at, last_message_at=last_at, updated_ts=time.time(),
        )

        state.update(
            status="ok", error=None, me=me, other=other, last_id=last_id,
            first_message_at=first_at, last_message_at=last_at,
            updated_ts=time.time(), sync_seconds=round(time.time() - started, 2),
            processed=processed,
        )
        log.info(
            "готово за %.1f с: я=%s, собеседник=%s, всего=%s",
            state["sync_seconds"], me, other, me + other,
        )


async def initial_sync() -> None:
    """Первый пересчёт после входа — в фоне, чтобы сервис отвечал сразу."""
    try:
        await sync_once()
    except Exception as exc:
        state["status"] = "error"
        state["error"] = str(exc)
        log.error("первый пересчёт не удался: %s", exc)


async def sync_loop() -> None:
    while True:
        try:
            if client is not None and not state["is_bot"]:
                if await client.is_user_authorized():
                    await sync_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["status"] = "error"
            state["error"] = "%s" % exc
            log.exception("ошибка синхронизации")
        await asyncio.sleep(SYNC_INTERVAL)


async def ensure_fresh(max_wait: float = 8.0) -> None:
    """Обновляет данные по запросу сайта, но не чаще cooldown и без зависания."""
    fresh = time.time() - float(state["updated_ts"] or 0) < ON_DEMAND_COOLDOWN
    if state["status"] in ("syncing", "login") or fresh or client is None or state["is_bot"]:
        return
    try:
        await asyncio.wait_for(sync_once(), timeout=max_wait)
    except asyncio.TimeoutError:
        asyncio.create_task(sync_once())        # долгий пересчёт — продолжим в фоне
    except Exception:
        log.exception("не удалось обновить по запросу")


# ─────────────────────────── ответы API ───────────────────────────

def payload() -> Dict[str, Any]:
    me, other = int(state["me"] or 0), int(state["other"] or 0)
    total = me + other
    pct = lambda x: round(x / total * 100, 1) if total else 0.0
    return {
        "status": state["status"],
        "error": state["error"],
        "login_required": state["status"] == "login",
        "login_url": (PUBLIC_URL + "/login") if (PUBLIC_URL and LOGIN_SECRET) else None,
        "chat": {
            "title": TARGET_NAME or state["title"] or TARGET_PHONE,
            "phone": TARGET_PHONE,
        },
        "me": {"name": MY_NAME, "messages": me, "percent": pct(me)},
        "other": {"name": TARGET_NAME or state["title"] or "Собеседник", "messages": other, "percent": pct(other)},
        "total": total,
        "first_message_at": state["first_message_at"],
        "last_message_at": state["last_message_at"],
        "updated_at": (
            datetime.fromtimestamp(state["updated_ts"], tz=timezone.utc).isoformat()
            if state["updated_ts"] else None
        ),
        "sync_seconds": state["sync_seconds"],
        "progress": {"processed": state["processed"]} if state["status"] == "syncing" else None,
    }


def stats_text() -> str:
    """Текст статистики для Telegram — как в исходном скрипте."""
    data = payload()
    me, other, total = data["me"]["messages"], data["other"]["messages"], data["total"]
    name = data["other"]["name"] or "Собеседник"
    line = "─" * 25
    return (
        "📊 Статистика переписки\n"
        f"{line}\n"
        f"✉️ Я отправил: {me} сообщений\n"
        f"💬 {name} отправила: {other} сообщений\n"
        f"{line}\n"
        f"📨 Всего: {total} сообщений\n\n"
        f"📈 Моя активность: {round(me / total * 100) if total else 0}%\n"
        f"📉 Активность {name}: {round(other / total * 100) if total else 0}%"
    )


async def on_trigger(event) -> None:
    """Ответ на слово-триггер (по умолчанию «инфо») в нашем чате."""
    entity = state["entity"]
    if entity is None:
        return
    if int(event.chat_id) != int(entity.id):
        return                                  # пишем только в тот самый чат
    text = (event.raw_text or "").strip()
    if text.lower() != TRIGGER_WORD.lower():
        return

    log.info("триггер «%s» — отправляю статистику в чат", TRIGGER_WORD)
    try:
        await sync_once()
    except Exception:
        log.exception("не удалось обновить перед ответом")
    try:
        await event.edit(stats_text())           # заменяет само сообщение «инфо»
    except Exception:
        try:
            await event.reply(stats_text())
        except Exception:
            log.exception("не смог отправить статистику в Telegram")


def register_handlers() -> None:
    if state["handlers_added"] or client is None:
        return
    client.add_event_handler(on_trigger, events.NewMessage(outgoing=True))
    state["handlers_added"] = True
    log.info("триггер в чате: «%s»", TRIGGER_WORD)


# ─────────────────────────── запуск / остановка ───────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    task = None

    load_from_db()

    # строка сессии: сначала переменная окружения, затем та, что сохранила страница входа
    session, problem = "", None
    for source, raw in (("TG_SESSION", TG_SESSION), ("база (страница входа)", db_get("tg_session") or "")):
        candidate = clean_session(raw)
        if not candidate:
            continue
        issue = session_problem(candidate)
        if issue:
            problem = issue
            log.error("строка сессии из %s не подходит: %s", source, issue)
            continue
        session = candidate
        log.info("беру сессию из %s", source)
        break

    if not (API_ID and API_HASH):
        state["status"] = "error"
        state["error"] = "Не заданы API_ID / API_HASH в переменных окружения (ключи с my.telegram.org)."
        log.error(state["error"])
    else:
        client = TelegramClient(
            StringSession(session), API_ID, API_HASH,
            connection_retries=10, retry_delay=3, timeout=30,
            request_retries=5, flood_sleep_threshold=120,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                state["status"] = "login"
                state["error"] = ("Переменная TG_SESSION задана неверно: %s. %s" % (problem, login_hint())) \
                    if problem else login_hint()
                log.warning("нет входа в Telegram: %s", state["error"])
            else:
                me = await client.get_me()
                state["is_bot"] = bool(getattr(me, "bot", False))
                log.info("авторизован как %s (@%s)%s",
                         me.first_name, me.username, " — БОТ" if state["is_bot"] else "")
                if state["is_bot"]:
                    state["status"] = "error"
                    state["error"] = BOT_SESSION_HINT % (PUBLIC_URL or "")
                    log.error("сессия бота (@%s) не подходит: %s", me.username, state["error"])
                    if LOGIN_SECRET:
                        log.error("войди аккаунтом: %s/login?secret=<LOGIN_SECRET>", PUBLIC_URL or "адрес сервиса")
                else:
                    register_handlers()
                    state["status"] = "syncing"
                    asyncio.create_task(initial_sync())
        except Exception as exc:
            state["status"] = "error"
            state["error"] = "Не удалось подключиться к Telegram: %s" % exc
            log.exception("ошибка подключения")

    task = asyncio.create_task(sync_loop())

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if client is not None:
        await client.disconnect()


app = FastAPI(title="Статистика переписки", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ═══════════════════════ вход в Telegram через браузер ═══════════════════════

def esc(value: Any) -> str:
    return html_mod.escape(str(value if value is not None else ""))


PAGE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:
 radial-gradient(120% 90% at 50% -10%,#1b0f2c 0,transparent 60%),
 linear-gradient(160deg,#08060f,#0d0718 45%,#06040c);color:#efeaf7;min-height:100vh;
 padding:24px 16px;display:flex;justify-content:center;align-items:flex-start}
.wrap{width:100%;max-width:620px;background:rgba(18,12,30,.74);border:1px solid rgba(255,255,255,.1);
 border-radius:26px;padding:30px 26px;box-shadow:0 30px 80px -30px rgba(0,0,0,.9)}
h1{font-family:Georgia,serif;font-weight:400;font-size:25px;margin-bottom:14px;line-height:1.3}
h1 em{font-style:italic;background:linear-gradient(100deg,#ff3d81,#a06bff 45%,#5ee7ff);
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
p{color:#a89fc0;line-height:1.7;font-size:15px;margin-bottom:12px}
ol,ul{margin:0 0 16px 20px;color:#a89fc0;line-height:1.75;font-size:15px}
b{color:#fff}
a{color:#ff8ab6}
.qr{display:grid;place-items:center;margin:18px 0;padding:16px;border-radius:20px;
 background:#0b0714;border:1px solid rgba(255,255,255,.1)}
.qr svg{width:100%;max-width:300px;height:auto;display:block}
.status{text-align:center;font-size:14px;color:#ff8ab6;min-height:20px}
form{display:grid;gap:12px;margin-top:16px}
label{font-size:13px;color:#a89fc0;letter-spacing:.4px}
input{width:100%;padding:13px 16px;border-radius:14px;border:1px solid rgba(255,255,255,.14);
 background:rgba(255,255,255,.05);color:#fff;font-size:16px;font-family:inherit}
input:focus{outline:none;border-color:rgba(255,61,129,.6)}
button{cursor:pointer;padding:14px 22px;border:none;border-radius:999px;font-size:15px;font-weight:600;
 font-family:inherit;color:#fff;background:linear-gradient(135deg,#ff3d81,#a06bff);
 box-shadow:0 16px 34px -16px rgba(255,61,129,.85);transition:transform .2s,box-shadow .2s}
button:hover{transform:translateY(-2px)}
.ghost{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.16);box-shadow:none}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}
.err{padding:14px 16px;border-radius:14px;background:rgba(255,61,129,.12);
 border:1px solid rgba(255,61,129,.35);color:#ffc7da;font-size:14px;margin-bottom:14px}
.ok{padding:14px 16px;border-radius:14px;background:rgba(94,231,255,.1);
 border:1px solid rgba(94,231,255,.3);color:#c9f4ff;font-size:14px;margin-bottom:14px}
textarea{width:100%;min-height:110px;padding:13px;border-radius:14px;border:1px solid rgba(255,255,255,.14);
 background:rgba(0,0,0,.35);color:#c9f4ff;font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all}
.hint{font-size:13px;color:#a89fc0;margin-top:10px;line-height:1.65}
hr{border:none;border-top:1px dashed rgba(255,255,255,.12);margin:22px 0}
"""


def page(title: str, body: str, status: int = 200, script: str = "") -> HTMLResponse:
    doc = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap"><h1>{title}</h1>{body}</div>{script}</body></html>"""
    return HTMLResponse(doc, status_code=status)


def secret_ok(secret: str) -> bool:
    return bool(LOGIN_SECRET) and pysecrets.compare_digest(secret or "", LOGIN_SECRET)


def secret_page() -> HTMLResponse:
    if not LOGIN_SECRET:
        return page("Вход не настроен", """
<div class="err">Не задана переменная <b>LOGIN_SECRET</b>.</div>
<p>Чтобы включить вход в Telegram через браузер:</p>
<ol>
  <li>Render → сервис статистики → <b>Environment</b> → <b>Add Environment Variable</b></li>
  <li>Key: <b>LOGIN_SECRET</b>, Value: любое секретное слово (например, <b>anya-2026</b>)</li>
  <li>Сохранить — сервис перезапустится сам</li>
  <li>Открыть <b>/login?secret=anya-2026</b> и отсканировать QR телефоном</li>
</ol>""", status=403)
    return page("Неверный ключ доступа", """
<div class="err">Секрет не совпадает с переменной <b>LOGIN_SECRET</b>.</div>
<p>Открой страницу так: <b>/login?secret=твоё_слово</b> — то же слово, что указано
в переменной <b>LOGIN_SECRET</b> в Render.</p>""", status=403)


def qr_svg(data: str) -> str:
    """QR-код в виде SVG прямо в HTML — без внешних картинок."""
    try:
        import segno
    except ImportError:
        return "<p class='err'>Модуль segno не установлен: добавь его в requirements.txt</p>"
    buf = io.BytesIO()
    segno.make(data, error="m").save(
        buf, kind="svg", scale=4, border=2, dark="#ffffff", light=None,
        xmldecl=False, svgns=True, nl=False,
    )
    svg = buf.getvalue().decode("utf-8")
    return svg.replace("<svg ", '<svg style="width:100%;max-width:300px;height:auto" ', 1)


def qr_page() -> HTMLResponse:
    body = """
<p>Открой Telegram на телефоне: <b>Настройки → Устройства → Подключить устройство</b>
и наведи камеру на код. Код подтверждения вводить не нужно — вход произойдёт сразу.</p>
<div class="qr" id="qrbox"><span style="color:#a89fc0">создаю QR-код…</span></div>
<div class="status" id="status">подключаюсь к Telegram…</div>
<hr>
<p class="hint">QR-код обновляется сам каждые полминуты. Если телефон не может отсканировать —
можно войти кодом: <a href="/login?secret=__SECRET__&amp;mode=code">ввести код из Telegram</a>.
А если у аккаунта включён облачный пароль, страница попросит его после сканирования.</p>
"""
    script = """<script>
var secret = new URLSearchParams(location.search).get('secret') || '';
var shown = -1, done = false;
document.body.innerHTML = document.body.innerHTML.replace('__SECRET__', encodeURIComponent(secret));

async function tick() {
  if (done) return;
  try {
    var r = await fetch('/login/qr/status?secret=' + encodeURIComponent(secret)).then(function (x) { return x.json(); });
    if (r.state === 'waiting') {
      if (r.version !== shown) { document.getElementById('qrbox').innerHTML = r.svg; shown = r.version; }
      document.getElementById('status').textContent = 'Ожидаю сканирования…';
    } else if (r.state === 'password') {
      document.getElementById('status').textContent = 'Нужен облачный пароль — введи его ниже';
      document.getElementById('pwform').style.display = 'grid';
      done = true;
    } else if (r.state === 'done') {
      document.getElementById('status').textContent = 'Готово! Вход выполнен ✅';
      document.getElementById('donebox').innerHTML = r.done_html;
      done = true;
    } else if (r.state === 'error') {
      document.getElementById('status').textContent = 'Ошибка: ' + (r.error || 'неизвестная');
      done = true;
    }
  } catch (e) {
    document.getElementById('status').textContent = 'Сервер просыпается…';
  }
}
setInterval(tick, 2500); tick();
</script>"""
    body += """
<form id="pwform" action="/login/password" method="post" style="display:none">
  <input type="hidden" name="secret" value="__SECRET__">
  <label>Облачный пароль (двухфакторка)</label>
  <input type="password" name="password" placeholder="пароль" autocomplete="current-password">
  <button type="submit">Войти</button>
</form>
<div id="donebox"></div>
"""
    return page("Вход в Telegram по <em>QR-коду</em>", body, script=script)


def done_html(session: str) -> str:
    return f"""
<div class="ok">Вход выполнен. Сервис уже считает сообщения — обнови страницу сайта.</div>
<p class="hint">Чтобы вход сохранился после пересборки сервиса, вставь эту строку в Render →
сервис статистики → Environment → переменная <b>TG_SESSION</b>:</p>
<textarea readonly onclick="this.select()">{esc(session)}</textarea>
<p class="hint">Проверить: <a href="/api/stats" target="_blank">/api/stats</a> ·
<a href="/api/health" target="_blank">/api/health</a></p>
"""


def session_page() -> HTMLResponse:
    """Сессия уже есть — показываем строку и предлагаем войти другим аккаунтом."""
    session = client.session.save() if client is not None else ""
    who = "неизвестно"
    return page("Вход в Telegram уже выполнен", f"""
<div class="ok">Сервис авторизован и считает сообщения. Ничего делать не нужно.</div>
<p class="hint">Строка сессии (её можно положить в переменную <b>TG_SESSION</b>, чтобы вход
сохранился после пересборки сервиса):</p>
<textarea readonly onclick="this.select()">{esc(session)}</textarea>
<div class="row">
  <a class="ghost" style="text-decoration:none;padding:13px 20px;border-radius:999px"
     href="/login?secret={esc(LOGIN_SECRET)}&amp;switch=1">Войти другим аккаунтом</a>
</div>
<p class="hint">Вход другим аккаунтом сначала завершит текущий сеанс.</p>
""")


def options_page() -> HTMLResponse:
    """Выбор способа входа: QR или код."""
    return page("Вход в Telegram", """
<p>Выбери способ — оба ведут к одному результату. Проще всего QR-код: код подтверждения
вводить не придётся.</p>
<form action="/login/qr" method="post">
  <input type="hidden" name="secret" value="__SECRET__">
  <button type="submit">Показать QR-код для сканирования</button>
</form>
<hr>
<p class="hint">Второй вариант — код из Telegram. Номер вводи в международном формате
(<b>+380…</b>). Код придёт сообщением от «Telegram» (или по SMS, если других активных
устройств нет).</p>
<form action="/login/phone" method="post">
  <input type="hidden" name="secret" value="__SECRET__">
  <label>Номер телефона аккаунта, где есть ваша переписка</label>
  <input name="phone" value="__PHONE__" placeholder="+380XXXXXXXXX" autocomplete="tel">
  <button class="ghost" type="submit">Прислать код в Telegram</button>
</form>
""".replace("__SECRET__", esc(LOGIN_SECRET)).replace("__PHONE__", esc(TARGET_PHONE)))


def code_page(phone: str, code_hash: str, error: str = "") -> HTMLResponse:
    body = ("<div class='err'>%s</div>" % esc(error)) if error else ""
    body += """
<p>Telegram отправил код. Посмотри чат с официальным аккаунтом <b>Telegram</b> (или SMS).
Введи код ниже.</p>
<form action="/login/code" method="post">
  <input type="hidden" name="secret" value="__SECRET__">
  <input type="hidden" name="phone" value="__PHONE__">
  <input type="hidden" name="phone_code_hash" value="__HASH__">
  <label>Код из Telegram</label>
  <input name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="12345" autofocus>
  <button type="submit">Войти</button>
</form>
<hr>
<p class="hint">Код не приходит? Не запрашивай его много раз подряд (Telegram временно
блокирует запросы). Надёжнее вернуться к <a href="/login?secret=__SECRET__">QR-коду</a> —
там код вообще не нужен.</p>
"""
    body = (body.replace("__SECRET__", esc(LOGIN_SECRET))
                .replace("__PHONE__", esc(phone))
                .replace("__HASH__", esc(code_hash)))
    return page("Введи <em>код</em> из Telegram", body)


def password_page(error: str = "") -> HTMLResponse:
    body = ("<div class='err'>%s</div>" % esc(error)) if error else ""
    body += """
<p>У аккаунта включён облачный пароль (двухфакторная аутентификация). Введи его,
чтобы завершить вход.</p>
<form action="/login/password" method="post">
  <input type="hidden" name="secret" value="__SECRET__">
  <label>Облачный пароль</label>
  <input type="password" name="password" autocomplete="current-password" autofocus>
  <button type="submit">Войти</button>
</form>
"""
    return page("Нужен <em>облачный</em> пароль", body.replace("__SECRET__", esc(LOGIN_SECRET)))


# ── шаги входа ──

async def complete_login(source: str) -> None:
    """Общая точка финиша: сохранить сессию, запустить пересчёт."""
    session = client.session.save()
    db_set("tg_session", session)
    state.update(status="syncing", error=None, is_bot=False)
    login_state.update(qr_state="done", session=session, qr_error=None)
    register_handlers()
    asyncio.create_task(initial_sync())
    log.info("вход выполнен (%s)", source)


async def qr_worker() -> None:
    """Крутит QR-вход: создаёт код, обновляет по таймауту, завершает вход."""
    try:
        await client.connect()
        qr = await client.qr_login()
        login_state.update(qr_state="waiting", qr_url=qr.url, qr_error=None,
                           qr_version=login_state["qr_version"] + 1)
        log.info("QR-код создан, жду сканирования")
    except Exception as exc:
        login_state.update(qr_state="error", qr_error="Не удалось создать QR-код: %s" % exc)
        log.exception("ошибка создания QR")
        return

    while True:
        try:
            await qr.wait(timeout=30)
            break
        except (asyncio.TimeoutError, TimeoutError):
            try:
                qr = await qr.recreate()
                login_state.update(qr_url=qr.url, qr_version=login_state["qr_version"] + 1)
                log.info("QR-код обновлён")
            except Exception as exc:
                login_state.update(qr_state="error", qr_error="QR истёк и не обновился: %s" % exc)
                return
        except errors.SessionPasswordNeededError:
            login_state.update(qr_state="password")
            log.info("нужен облачный пароль")
            return
        except Exception as exc:
            login_state.update(qr_state="error", qr_error=str(exc))
            log.exception("ошибка QR-входа")
            return

    await complete_login("QR-код")


@app.get("/login", response_class=HTMLResponse)
async def login_page(secret: str = Query(""), switch: int = 0):
    if not secret_ok(secret):
        return secret_page()

    if client is None:
        return page("Вход невозможен", """
<div class="err">Не заданы <b>API_ID</b> и <b>API_HASH</b>.</div>
<p>Добавь их в Render → Environment (ключи с <b>my.telegram.org</b>) и перезапусти сервис.
После этого эта страница заработает.</p>""", status=400)

    if switch and await client.is_user_authorized():
        await client.log_out()
        state.update(entity=None, title=None, is_bot=False, handlers_added=False)
        login_state.update(qr_state="idle", session=None)
        log.info("выполнен выход из аккаунта по запросу")

    if await client.is_user_authorized() and not state["is_bot"]:
        return session_page()

    if state["is_bot"]:
        # бот-сессию надо снять, иначе войти человеком нельзя
        try:
            await client.log_out()
            state.update(is_bot=False, error=None, handlers_added=False)
            log.info("бот-сессия завершена, можно войти аккаунтом")
        except Exception:
            log.exception("не смог завершить бот-сессию")

    return options_page()


@app.post("/login/qr", response_class=HTMLResponse)
async def login_qr_start(secret: str = Form("")):
    if not secret_ok(secret):
        return secret_page()
    if client is None:
        return page("Вход невозможен", "<div class='err'>Не заданы API_ID и API_HASH.</div>", status=400)

    task = login_state.get("qr_task")
    if task and not task.done():
        task.cancel()
    login_state["qr_task"] = asyncio.create_task(qr_worker())
    return qr_page()


@app.get("/login/qr/status")
async def login_qr_status(secret: str = Query("")):
    if not secret_ok(secret):
        return JSONResponse({"state": "error", "error": "неверный secret"}, status_code=403)

    svg = qr_svg(login_state["qr_url"]) if (login_state["qr_url"] and login_state["qr_state"] in ("waiting", "idle")) else ""
    result = {
        "state": login_state["qr_state"],
        "version": login_state["qr_version"],
        "svg": svg,
        "error": login_state["qr_error"],
    }
    if login_state["qr_state"] == "done" and login_state["session"]:
        result["done_html"] = done_html(login_state["session"])
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/login/phone", response_class=HTMLResponse)
async def login_phone(secret: str = Form(""), phone: str = Form("")):
    if not secret_ok(secret):
        return secret_page()
    if client is None:
        return page("Вход невозможен", "<div class='err'>Не заданы API_ID и API_HASH.</div>", status=400)

    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + digits(phone)

    if time.time() - login_state["last_code_request"] < 25:
        again = int(25 - (time.time() - login_state["last_code_request"]))
        return code_page(phone, login_state["hash"] or "",
                         "Подожди %s сек перед повторным запросом кода." % again)

    if session_problem(clean_session(TG_SESSION)):
        log.info("переменная TG_SESSION содержит нерабочую строку — вход по коду её заменит")
        db_set("tg_session", "")

    try:
        await client.connect()
        sent = await client.send_code_request(phone)
    except errors.FloodWaitError as exc:
        return code_page(phone, "", "Telegram просит подождать %s секунд." % exc.seconds)
    except errors.PhoneNumberInvalidError:
        return code_page(phone, "", "Номер не принят Telegram. Формат: +380XXXXXXXXX")
    except Exception as exc:
        return code_page(phone, "", "Не удалось отправить код: %s" % exc)

    login_state.update(phone=phone, hash=sent.phone_code_hash, last_code_request=time.time())
    return code_page(phone, sent.phone_code_hash)


@app.post("/login/code", response_class=HTMLResponse)
async def login_code(secret: str = Form(""), phone: str = Form(""),
                     code: str = Form(""), phone_code_hash: str = Form("")):
    if not secret_ok(secret):
        return secret_page()

    code = code.strip().replace(" ", "")
    try:
        await client.sign_in(phone=phone, code=code,
                             phone_code_hash=phone_code_hash or login_state["hash"])
    except errors.SessionPasswordNeededError:
        return password_page()
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError) as exc:
        return code_page(phone, phone_code_hash, "Код не подошёл (%s). Попробуй ещё раз." % exc)
    except Exception as exc:
        return code_page(phone, phone_code_hash, "Не удалось войти: %s" % exc)

    await complete_login("код из Telegram")
    return page("Готово! ❤️", done_html(login_state["session"] or ""))


@app.post("/login/password", response_class=HTMLResponse)
async def login_password(secret: str = Form(""), password: str = Form("")):
    if not secret_ok(secret):
        return secret_page()
    try:
        await client.sign_in(password=password)
    except errors.PasswordHashInvalidError:
        return password_page("Пароль не подошёл. Попробуй снова.")
    except Exception as exc:
        return password_page("Не удалось войти: %s" % exc)

    await complete_login("QR + облачный пароль")
    return page("Готово! ❤️", done_html(login_state["session"] or ""))


@app.get("/api/stats")
async def api_stats(refresh: int = 0):
    if refresh:
        state["updated_ts"] = 0            # принудительно обновить (уважая lock)
    await ensure_fresh()
    return JSONResponse(payload(), headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/health")
async def health():
    return {
        "ok": state["status"] in ("ok", "syncing"),
        "status": state["status"],
        "error": state["error"],
        "login_required": state["status"] == "login",
        "updated_at": payload()["updated_at"],
        "total": state["me"] + state["other"],
    }


@app.get("/")
async def root():
    return {
        "service": "статистика переписки",
        "stats": "/api/stats",
        "health": "/api/health",
        "login": "/login?secret=<LOGIN_SECRET>",
        "status": state["status"],
        "error": state["error"],
    }
