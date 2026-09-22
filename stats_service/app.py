"""
Сервис статистики переписки — API для сайта.

Что делает:
  • держит авторизованную сессию Telegram (Telethon) и считает сообщения
    только в одном чате (по умолчанию +380669543625);
  • хранит счётчики в SQLite и досчитывает новые сообщения инкрементально
    (по последнему id), поэтому после перезапуска ничего не теряется;
  • отдаёт готовые цифры сайту: GET /api/stats

Переменные окружения (задаются в Render → Environment):
  API_ID, API_HASH   — с https://my.telegram.org
  TG_SESSION         — StringSession (генерируется локально: make_session.py)
  TARGET_PHONE       — чей чат считаем (по умолчанию +380669543625)
  TARGET_NAME        — как называть собеседницу на сайте (необязательно)
  MY_NAME            — как называть себя (по умолчанию «Я»)
  TRIGGER_WORD       — слово в чате, на которое сервис отвечает цифрами (по умолчанию «инфо»)
  SYNC_INTERVAL      — как часто досчитывать, секунд (по умолчанию 60)
  ON_DEMAND_COOLDOWN — не чаще, чем раз в N секунд обновлять по запросу сайта
  ALLOWED_ORIGINS    — список источников через запятую или * (по умолчанию *)
  DB_PATH            — путь к файлу базы (по умолчанию stats.db рядом с кодом)
"""

import asyncio
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stats")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


API_ID = int(env("API_ID", "0") or 0)
API_HASH = env("API_HASH")
TG_SESSION = env("TG_SESSION")
TARGET_PHONE = env("TARGET_PHONE", "+380669543625")
TARGET_NAME = env("TARGET_NAME") or None
MY_NAME = env("MY_NAME") or "Я"
SYNC_INTERVAL = int(env("SYNC_INTERVAL", "60") or 60)
ON_DEMAND_COOLDOWN = int(env("ON_DEMAND_COOLDOWN", "25") or 25)
DIALOG_SCAN_LIMIT = int(env("DIALOG_SCAN_LIMIT", "400") or 400)
TRIGGER_WORD = env("TRIGGER_WORD", "инфо")           # слово в чате, на которое отвечаем цифрами
MAX_HISTORY = int(env("MAX_HISTORY", "0") or 0) or None      # 0 = вся история
DB_PATH = env("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.db"))
ALLOWED_ORIGINS = [o.strip() for o in env("ALLOWED_ORIGINS", "*").split(",") if o.strip()] or ["*"]


state: Dict[str, Any] = {
    "status": "starting",     # starting | ok | syncing | error
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
    "lock": asyncio.Lock(),
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
    """Находит собеседника: сначала по телефону, затем перебором диалогов."""
    global client
    if state["entity"] is not None and not force:
        return state["entity"]

    # 1) пробуем напрямую по номеру телефона
    try:
        entity = await client.get_entity(TARGET_PHONE)
        state["entity"] = entity
        state["title"] = TARGET_NAME or getattr(entity, "first_name", None) or TARGET_PHONE
        log.info("нашёл чат напрямую: %s", state["title"])
        return entity
    except Exception as exc:
        log.info("по номеру не нашлось (%s), перебираю диалоги…", type(exc).__name__)

    # 2) перебираем диалоги и сравниваем номер телефона
    async for dialog in client.iter_dialogs(limit=DIALOG_SCAN_LIMIT):
        ent = dialog.entity
        if getattr(ent, "bot", False):
            continue
        if phone_matches(getattr(ent, "phone", None)):
            state["entity"] = ent
            state["title"] = TARGET_NAME or getattr(ent, "first_name", None) or dialog.name or TARGET_PHONE
            log.info("нашёл чат среди диалогов: %s (id=%s)", state["title"], ent.id)
            return ent

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


async def sync_loop() -> None:
    while True:
        try:
            await sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            state["status"] = "error"
            state["error"] = "Синхронизация не удалась — смотри логи сервиса."
            log.exception("ошибка синхронизации")
        await asyncio.sleep(SYNC_INTERVAL)


async def ensure_fresh(max_wait: float = 8.0) -> None:
    """Обновляет данные по запросу сайта, но не чаще cooldown и без зависания."""
    fresh = time.time() - float(state["updated_ts"] or 0) < ON_DEMAND_COOLDOWN
    if state["status"] == "syncing" or fresh or client is None:
        return
    try:
        await asyncio.wait_for(sync_once(), timeout=max_wait)
    except asyncio.TimeoutError:
        asyncio.create_task(sync_once())        # долгий пересчёт — продолжим в фоне
    except Exception:
        log.exception("не удалось обновить по запросу")


# ─────────────────────────────── API ───────────────────────────────

def payload() -> Dict[str, Any]:
    me, other = int(state["me"] or 0), int(state["other"] or 0)
    total = me + other
    pct = lambda x: round(x / total * 100, 1) if total else 0.0
    return {
        "status": state["status"],
        "error": state["error"],
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    task = None

    load_from_db()

    if not (API_ID and API_HASH and TG_SESSION):
        state["status"] = "error"
        state["error"] = "Не заданы API_ID / API_HASH / TG_SESSION в переменных окружения."
        log.error(state["error"])
    else:
        client = TelegramClient(
            StringSession(TG_SESSION), API_ID, API_HASH,
            connection_retries=10, retry_delay=3, timeout=30,
            request_retries=5, flood_sleep_threshold=120,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                state["status"] = "error"
                state["error"] = "Сессия TG_SESSION недействительна — сгенерируй новую через make_session.py."
                log.error(state["error"])
            else:
                me = await client.get_me()
                log.info("авторизован как %s (@%s)", me.first_name, me.username)
                client.add_event_handler(on_trigger, events.NewMessage(outgoing=True))
                log.info("триггер в чате: «%s»", TRIGGER_WORD)
                await resolve_entity()
                try:
                    await sync_once()
                except Exception:
                    log.exception("первый пересчёт не удался, продолжу в фоне")
                task = asyncio.create_task(sync_loop())
        except Exception as exc:
            state["status"] = "error"
            state["error"] = "Не удалось подключиться к Telegram: %s" % exc
            log.exception("ошибка подключения")

    yield

    if task:
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
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


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
        "updated_at": payload()["updated_at"],
        "total": state["me"] + state["other"],
    }


@app.get("/")
async def root():
    return {
        "service": "статистика переписки",
        "stats": "/api/stats",
        "health": "/api/health",
        "status": state["status"],
    }
