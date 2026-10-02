"""
Сервис статистики переписки — API для сайта.

Что делает:
  • держит авторизованную сессию Telegram (Telethon) и считает сообщения
    только в одном чате (по умолчанию +380669543625);
  • хранит счётчики в SQLite и досчитывает новые сообщения инкрементально
    (по последнему id), поэтому после перезапуска ничего не теряется;
  • отдаёт готовые цифры сайту: GET /api/stats
  • отдаёт динамику по дням для графика: GET /api/series
  • отдаёт любовь-метрику: GET /api/love  (сколько «люблю», дни вместе)

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
  DATING_START       — дата начала отношений YYYY-MM-DD (по умолчанию 2026-09-13)
"""

import asyncio
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta, date
from typing import Any, Dict, Optional, List

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = None

from fastapi import FastAPI, Query
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
DEMO_MODE = env("DEMO_MODE", "0") == "1"
DATING_START_STR = env("DATING_START", "2026-09-13")
try:
    DATING_START = date.fromisoformat(DATING_START_STR)
except Exception:
    DATING_START = date(2026, 9, 13)

# слово-триггер для любви
LOVE_WORD = "люблю"


state: Dict[str, Any] = {
    "status": "starting",     # starting | ok | syncing | error
    "error": None,
    "entity": None,
    "title": None,
    "me": 0,
    "other": 0,
    "love_me": 0,
    "love_other": 0,
    "last_id": 0,
    "first_message_at": None,
    "last_message_at": None,
    "updated_ts": 0.0,
    "sync_seconds": None,
    "processed": 0,
    "lock": asyncio.Lock(),
}


# ────────────────────────────── база ──────────────────────────────

def _ensure_love_columns(conn: sqlite3.Connection):
    """Добавляет колонки любви если их нет (миграция старых баз)."""
    # chat_stats
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_stats)").fetchall()]
        if "love_me" not in cols:
            conn.execute("ALTER TABLE chat_stats ADD COLUMN love_me INTEGER DEFAULT 0")
        if "love_other" not in cols:
            conn.execute("ALTER TABLE chat_stats ADD COLUMN love_other INTEGER DEFAULT 0")
    except Exception:
        pass
    # daily_stats
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_stats)").fetchall()]
        if "love_me" not in cols:
            conn.execute("ALTER TABLE daily_stats ADD COLUMN love_me INTEGER DEFAULT 0")
        if "love_other" not in cols:
            conn.execute("ALTER TABLE daily_stats ADD COLUMN love_other INTEGER DEFAULT 0")
        if "love_total" not in cols:
            conn.execute("ALTER TABLE daily_stats ADD COLUMN love_total INTEGER DEFAULT 0")
    except Exception:
        pass


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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS daily_stats (
               date              TEXT PRIMARY KEY,
               me                INTEGER DEFAULT 0,
               other             INTEGER DEFAULT 0,
               total             INTEGER DEFAULT 0
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_stats(date)")
    _ensure_love_columns(conn)
    return conn


def db_read() -> Optional[sqlite3.Row]:
    try:
        with db() as conn:
            return conn.execute("SELECT * FROM chat_stats ORDER BY updated_ts DESC LIMIT 1").fetchone()
    except Exception:
        log.exception("не смог прочитать базу")
        return None


def db_write(**fields: Any) -> None:
    # убедимся что колонки есть
    with db() as conn:
        _ensure_love_columns(conn)
        cur = conn.execute("SELECT chat_id FROM chat_stats LIMIT 1").fetchone()
        # дефолты для любви если не передали
        fields.setdefault("love_me", 0)
        fields.setdefault("love_other", 0)
        if cur is None:
            conn.execute(
                """INSERT INTO chat_stats (chat_id, title, me, other, love_me, love_other, last_id,
                                           first_message_at, last_message_at, updated_ts)
                   VALUES (:chat_id, :title, :me, :other, :love_me, :love_other, :last_id,
                           :first_message_at, :last_message_at, :updated_ts)""",
                fields,
            )
        else:
            # проверяем есть ли колонки в существующей строке (на случай старой базы)
            conn.execute(
                """UPDATE chat_stats SET title = :title, me = :me, other = :other,
                       love_me = :love_me, love_other = :love_other,
                       last_id = :last_id, first_message_at = :first_message_at,
                       last_message_at = :last_message_at, updated_ts = :updated_ts
                   WHERE chat_id = :chat_id""",
                fields,
            )


def db_daily_write(counts: Dict[str, List[int]], force_full: bool = False) -> None:
    """Пишет агрегаты по дням. counts = {date: [me, other, love_me, love_other]}"""
    if not counts:
        return
    try:
        with db() as conn:
            _ensure_love_columns(conn)
            if force_full:
                conn.execute("DELETE FROM daily_stats")
                for d, vals in counts.items():
                    me_c = vals[0] if len(vals) > 0 else 0
                    other_c = vals[1] if len(vals) > 1 else 0
                    love_me = vals[2] if len(vals) > 2 else 0
                    love_other = vals[3] if len(vals) > 3 else 0
                    love_total = love_me + love_other
                    total = me_c + other_c
                    conn.execute(
                        "INSERT INTO daily_stats(date, me, other, total, love_me, love_other, love_total) VALUES (?,?,?,?,?,?,?)",
                        (d, me_c, other_c, total, love_me, love_other, love_total),
                    )
            else:
                for d, vals in counts.items():
                    me_c = vals[0] if len(vals) > 0 else 0
                    other_c = vals[1] if len(vals) > 1 else 0
                    love_me = vals[2] if len(vals) > 2 else 0
                    love_other = vals[3] if len(vals) > 3 else 0
                    love_total = love_me + love_other
                    total = me_c + other_c
                    # есть ли уже колонки love? если нет — упадёт, но мы их создали
                    conn.execute(
                        """INSERT INTO daily_stats(date, me, other, total, love_me, love_other, love_total)
                           VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(date) DO UPDATE SET
                             me = me + excluded.me,
                             other = other + excluded.other,
                             total = total + excluded.total,
                             love_me = love_me + excluded.love_me,
                             love_other = love_other + excluded.love_other,
                             love_total = love_total + excluded.love_total""",
                        (d, me_c, other_c, total, love_me, love_other, love_total),
                    )
    except Exception:
        log.exception("не смог записать daily_stats")


def db_daily_read_all() -> List[sqlite3.Row]:
    try:
        with db() as conn:
            _ensure_love_columns(conn)
            return list(conn.execute("SELECT date, me, other, total, love_me, love_other, love_total FROM daily_stats ORDER BY date ASC").fetchall())
    except Exception:
        log.exception("не смог прочитать daily_stats")
        return []


def db_daily_count() -> int:
    try:
        with db() as conn:
            r = conn.execute("SELECT COUNT(*) as c FROM daily_stats").fetchone()
            return int(r["c"] or 0) if r else 0
    except Exception:
        return 0


def load_from_db() -> bool:
    """Поднимает последние цифры из базы — чтобы сайт видел данные сразу после старта."""
    row = db_read()
    if row is None:
        return False
    # love колонки могут отсутствовать в старых базах
    try:
        lm = int(row["love_me"] or 0) if "love_me" in row.keys() else 0
    except Exception:
        lm = 0
    try:
        lo = int(row["love_other"] or 0) if "love_other" in row.keys() else 0
    except Exception:
        lo = 0
    state.update(
        me=int(row["me"] or 0),
        other=int(row["other"] or 0),
        love_me=lm,
        love_other=lo,
        last_id=int(row["last_id"] or 0),
        title=row["title"],
        first_message_at=row["first_message_at"],
        last_message_at=row["last_message_at"],
        updated_ts=float(row["updated_ts"] or 0),
    )
    log.info("поднял из базы: я=%s/%s люблю, собеседник=%s/%s люблю, daily_rows=%s", state["me"], state["love_me"], state["other"], state["love_other"], db_daily_count())
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

def _date_key(dt: datetime) -> str:
    """Конвертирует datetime сообщения в ключ YYYY-MM-DD в киевском времени если доступно, иначе UTC."""
    if dt is None:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if KYIV_TZ is not None:
            local = dt.astimezone(KYIV_TZ)
        else:
            local = dt.astimezone(timezone.utc)
        return local.date().isoformat()
    except Exception:
        try:
            return dt.astimezone(timezone.utc).date().isoformat()
        except Exception:
            return ""


def _contains_love(text: Optional[str]) -> bool:
    if not text:
        return False
    return LOVE_WORD in text.lower()


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
        # love из старой базы может отсутствовать
        try:
            love_me = 0 if force_full else int((row["love_me"] or 0) if "love_me" in row.keys() else 0)
            love_other = 0 if force_full else int((row["love_other"] or 0) if "love_other" in row.keys() else 0)
        except Exception:
            love_me = 0 if force_full else 0
            love_other = 0 if force_full else 0

        first_at = None if force_full else row["first_message_at"]
        last_at = None if force_full else row["last_message_at"]
        last_id = min_id
        processed = 0

        daily_counts: Dict[str, List[int]] = {}

        state["status"] = "syncing"
        state["processed"] = 0
        started = time.time()
        log.info("считаю чат «%s»: %s", title, "вся история" if force_full else "только новое")

        try:
            async for msg in client.iter_messages(entity, min_id=min_id, reverse=True, limit=MAX_HISTORY):
                last_id = max(last_id, msg.id)
                if msg.text is None and msg.media is None:
                    continue                                   # системное сообщение — не считаем
                is_me = bool(msg.out)
                text = msg.text or getattr(msg, "message", None) or ""
                is_love = _contains_love(text)

                if is_me:
                    me += 1
                    if is_love:
                        love_me += 1
                else:
                    other += 1
                    if is_love:
                        love_other += 1

                processed += 1
                state["processed"] = processed

                # дата для графика
                if msg.date:
                    stamp = msg.date.astimezone(timezone.utc).isoformat()
                    if first_at is None or stamp < first_at:
                        first_at = stamp
                    if last_at is None or stamp > last_at:
                        last_at = stamp
                    dk = _date_key(msg.date)
                    if dk:
                        if dk not in daily_counts:
                            daily_counts[dk] = [0, 0, 0, 0]
                        if is_me:
                            daily_counts[dk][0] += 1
                            if is_love:
                                daily_counts[dk][2] += 1
                        else:
                            daily_counts[dk][1] += 1
                            if is_love:
                                daily_counts[dk][3] += 1

                if processed % 500 == 0:
                    log.info("…обработано %s сообщений", processed)
                    await asyncio.sleep(0.05)
        except errors.FloodWaitError as exc:
            log.warning("Telegram просит подождать %s сек (FloodWait)", exc.seconds)
            state["status"] = "ok"
            raise

        # пишем агрегаты по дням
        if daily_counts:
            db_daily_write(daily_counts, force_full=force_full)
            log.info("daily: записал %s дней (%s)", len(daily_counts), "full" if force_full else "incr")

        db_write(
            chat_id=chat_id, title=title, me=me, other=other, love_me=love_me, love_other=love_other, last_id=last_id,
            first_message_at=first_at, last_message_at=last_at, updated_ts=time.time(),
        )

        state.update(
            status="ok", error=None, me=me, other=other, love_me=love_me, love_other=love_other, last_id=last_id,
            first_message_at=first_at, last_message_at=last_at,
            updated_ts=time.time(), sync_seconds=round(time.time() - started, 2),
            processed=processed,
        )
        log.info(
            "готово за %.1f с: я=%s/%s люблю, собеседник=%s/%s люблю, всего=%s",
            state["sync_seconds"], me, love_me, other, love_other, me + other,
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


# ─────────────────────────────── пайлоады ──────────────────────────────

def payload() -> Dict[str, Any]:
    me, other = int(state["me"] or 0), int(state["other"] or 0)
    love_me, love_other = int(state["love_me"] or 0), int(state["love_other"] or 0)
    total = me + other
    love_total = love_me + love_other
    pct = lambda x: round(x / total * 100, 1) if total else 0.0
    love_pct = lambda x: round(x / love_total * 100, 1) if love_total else 0.0
    return {
        "status": state["status"],
        "error": state["error"],
        "chat": {
            "title": TARGET_NAME or state["title"] or TARGET_PHONE,
            "phone": TARGET_PHONE,
        },
        "me": {"name": MY_NAME, "messages": me, "percent": pct(me), "love": love_me, "love_percent": love_pct(love_me)},
        "other": {"name": TARGET_NAME or state["title"] or "Собеседник", "messages": other, "percent": pct(other), "love": love_other, "love_percent": love_pct(love_other)},
        "total": total,
        "love_total": love_total,
        "first_message_at": state["first_message_at"],
        "last_message_at": state["last_message_at"],
        "updated_at": (
            datetime.fromtimestamp(state["updated_ts"], tz=timezone.utc).isoformat()
            if state["updated_ts"] else None
        ),
        "sync_seconds": state["sync_seconds"],
        "progress": {"processed": state["processed"]} if state["status"] == "syncing" else None,
    }


def days_together_payload() -> Dict[str, Any]:
    today = date.today()
    delta = (today - DATING_START).days
    # считаем включительно? с 13.09.2026 = день 1
    days_together = max(0, delta + 1)  # если сегодня 13.09.2026 => 1 день
    # красиво: годы/месяцы?
    return {
        "start": DATING_START.isoformat(),
        "today": today.isoformat(),
        "days": days_together,
        "delta": delta,
        "text": f"{days_together} { _plural(days_together, 'день', 'дня', 'дней') } вместе",
        "weeks": round(days_together / 7, 1),
    }


def _plural(n, one, few, many):
    m10 = n % 10; m100 = n % 100
    if m10 == 1 and m100 != 11:
        return one
    if m10 >= 2 and m10 <= 4 and (m100 < 10 or m100 >= 20):
        return few
    return many


def build_series(days: int = 90) -> Dict[str, Any]:
    """
    Собирает серию по дням для графика.
    days=0 -> вся история.
    Заполняет пропуски нулями, считает среднее, скользящее среднее 7д, просадки.
    """
    rows = db_daily_read_all()

    # если базы нет и демо включено — генерим синтетику для превью
    if not rows and DEMO_MODE:
        return _demo_series(days)

    # rows уже отсортированы по date ASC
    # map date -> counts
    data_map = {}
    for r in rows:
        try:
            data_map[r["date"]] = {"me": int(r["me"] or 0), "other": int(r["other"] or 0), "total": int(r["total"] or 0),
                                   "love_me": int(r["love_me"] or 0) if "love_me" in r.keys() else 0,
                                   "love_other": int(r["love_other"] or 0) if "love_other" in r.keys() else 0,
                                   "love_total": int(r["love_total"] or 0) if "love_total" in r.keys() else 0}
        except Exception:
            data_map[r["date"]] = {"me": int(r["me"] or 0), "other": int(r["other"] or 0), "total": int(r["total"] or 0), "love_me": 0, "love_other": 0, "love_total": 0}

    if not data_map:
        # пустая база — вернём пустую серию но с метаданными
        return {
            "status": state["status"],
            "error": state["error"],
            "updated_at": payload()["updated_at"],
            "granularity": "day",
            "days": days,
            "range": {"from": None, "to": None},
            "totals": {"me": state["me"], "other": state["other"], "total": state["me"]+state["other"]},
            "average_per_day": 0,
            "max": 0,
            "min": 0,
            "series": [],
            "moving_avg_7": [],
            "dips": [],
            "peaks": [],
            "streaks": {"current_zero_streak": 0, "longest_zero_streak": 0},
            "is_demo": False,
        }

    # определяем диапазон
    all_dates = sorted(data_map.keys())
    # Заполним пропуски от first_message_at до сегодня
    try:
        if state["first_message_at"]:
            first_d = datetime.fromisoformat(state["first_message_at"]).date().isoformat()
            if first_d < all_dates[0]:
                all_dates = [first_d] + all_dates
    except Exception:
        pass

    today = date.today().isoformat()
    last_date = all_dates[-1] if all_dates else today
    if last_date < today:
        pass

    # определим стартовую дату в зависимости от days
    if days and days > 0:
        # последние N дней включая сегодня
        end = date.today()
        start = end - timedelta(days=days - 1)
        start_s = start.isoformat()
        end_s = end.isoformat()
    else:
        # вся история: от минимума до максимума (или сегодня)
        start_s = all_dates[0]
        end_s = max(today, all_dates[-1])

    # генерируем полный список дат от start_s до end_s
    try:
        s_date = date.fromisoformat(start_s)
        e_date = date.fromisoformat(end_s)
    except Exception:
        s_date = date.fromisoformat(all_dates[0])
        e_date = date.fromisoformat(all_dates[-1])

    full_series: List[Dict[str, Any]] = []
    cur = s_date
    while cur <= e_date:
        ds = cur.isoformat()
        v = data_map.get(ds, {"me": 0, "other": 0, "total": 0, "love_me": 0, "love_other": 0, "love_total": 0})
        full_series.append({"date": ds, "me": v["me"], "other": v["other"], "total": v["total"],
                            "love_me": v["love_me"], "love_other": v["love_other"], "love_total": v["love_total"]})
        cur += timedelta(days=1)

    # считаем агрегаты
    totals = {"me": sum(x["me"] for x in full_series), "other": sum(x["other"] for x in full_series), "total": sum(x["total"] for x in full_series)}
    n_days = len(full_series) if full_series else 1
    avg = round(totals["total"] / n_days, 2) if n_days else 0
    active = [x["total"] for x in full_series if x["total"] > 0]
    avg_active = round(sum(active)/len(active), 2) if active else 0

    max_v = max((x["total"] for x in full_series), default=0)
    min_v = min((x["total"] for x in full_series), default=0)

    # скользящее среднее 7 дней
    moving = []
    for i, pt in enumerate(full_series):
        window = full_series[max(0, i-6): i+1]
        w_sum = sum(w["total"] for w in window)
        w_avg = round(w_sum / len(window), 2)
        moving.append({"date": pt["date"], "avg": w_avg})

    # детект просадок
    base = avg_active if avg_active > 0 else (avg if avg > 0 else 10)
    dips: List[Dict[str, Any]] = []
    for i, pt in enumerate(full_series):
        tot = pt["total"]
        local_avg = moving[i]["avg"] if i < len(moving) else base
        ref = max(base, local_avg, 5)
        is_zero_dip = (tot == 0 and ref >= 8)
        is_low_dip = (tot > 0 and tot < ref * 0.35 and ref >= 7)
        is_soft_dip = (tot > 0 and tot < ref * 0.5 and ref >= 12 and tot <= 6)
        if is_zero_dip or is_low_dip or is_soft_dip:
            severity = 0
            if tot == 0:
                severity = 1.0
            else:
                severity = max(0.0, min(1.0, 1 - tot / ref))
            label = "тишина" if tot == 0 else "просадка"
            diff = int(ref - tot)
            dips.append({
                "date": pt["date"],
                "total": tot,
                "me": pt["me"],
                "other": pt["other"],
                "ref_avg": round(ref, 1),
                "diff": diff,
                "severity": round(severity, 2),
                "label": label,
            })

    peaks = sorted(full_series, key=lambda x: x["total"], reverse=True)[:5]
    peaks = [p for p in peaks if p["total"] > 0][:3]

    cur_streak = 0
    longest = 0
    tmp = 0
    for pt in reversed(full_series):
        if pt["total"] == 0:
            cur_streak += 1
        else:
            break
    for pt in full_series:
        if pt["total"] == 0:
            tmp += 1
            longest = max(longest, tmp)
        else:
            tmp = 0

    return {
        "status": state["status"],
        "error": state["error"],
        "updated_at": payload()["updated_at"],
        "granularity": "day",
        "days": days,
        "range": {"from": full_series[0]["date"] if full_series else None, "to": full_series[-1]["date"] if full_series else None},
        "totals": totals,
        "average_per_day": avg,
        "average_active_day": avg_active,
        "max": max_v,
        "min": min_v,
        "series": full_series,
        "moving_avg_7": moving,
        "dips": dips,
        "peaks": peaks,
        "streaks": {"current_zero_streak": cur_streak, "longest_zero_streak": longest},
        "is_demo": False,
        "tz": "Europe/Kyiv" if KYIV_TZ else "UTC",
    }


def build_love_series(days: int = 90) -> Dict[str, Any]:
    """Собирает серию только по «люблю»."""
    rows = db_daily_read_all()
    if not rows and DEMO_MODE:
        return _demo_love_series(days)

    data_map = {}
    for r in rows:
        try:
            data_map[r["date"]] = {
                "love_me": int(r["love_me"] or 0) if "love_me" in r.keys() else 0,
                "love_other": int(r["love_other"] or 0) if "love_other" in r.keys() else 0,
                "love_total": int(r["love_total"] or 0) if "love_total" in r.keys() else 0,
            }
        except Exception:
            data_map[r["date"]] = {"love_me": 0, "love_other": 0, "love_total": 0}

    if not data_map:
        return {
            "status": state["status"],
            "error": state["error"],
            "updated_at": payload()["updated_at"],
            "granularity": "day",
            "days": days,
            "range": {"from": None, "to": None},
            "totals": {"love_me": state["love_me"], "love_other": state["love_other"], "love_total": state["love_me"]+state["love_other"]},
            "average_per_day": 0,
            "max": 0,
            "min": 0,
            "series": [],
            "moving_avg_7": [],
            "peaks": [],
            "is_demo": False,
            "dating": days_together_payload(),
        }

    all_dates = sorted(data_map.keys())
    today = date.today().isoformat()

    if days and days > 0:
        end = date.today()
        start = end - timedelta(days=days - 1)
        start_s = start.isoformat()
        end_s = end.isoformat()
    else:
        start_s = all_dates[0]
        end_s = max(today, all_dates[-1])

    try:
        s_date = date.fromisoformat(start_s)
        e_date = date.fromisoformat(end_s)
    except Exception:
        s_date = date.fromisoformat(all_dates[0])
        e_date = date.fromisoformat(all_dates[-1])

    full_series: List[Dict[str, Any]] = []
    cur = s_date
    while cur <= e_date:
        ds = cur.isoformat()
        v = data_map.get(ds, {"love_me": 0, "love_other": 0, "love_total": 0})
        full_series.append({"date": ds, "love_me": v["love_me"], "love_other": v["love_other"], "love_total": v["love_total"]})
        cur += timedelta(days=1)

    totals = {"love_me": sum(x["love_me"] for x in full_series), "love_other": sum(x["love_other"] for x in full_series), "love_total": sum(x["love_total"] for x in full_series)}
    n_days = len(full_series) if full_series else 1
    avg = round(totals["love_total"] / n_days, 2) if n_days else 0
    active = [x["love_total"] for x in full_series if x["love_total"] > 0]
    avg_active = round(sum(active)/len(active), 2) if active else 0
    max_v = max((x["love_total"] for x in full_series), default=0)
    min_v = min((x["love_total"] for x in full_series), default=0)

    moving = []
    for i, pt in enumerate(full_series):
        window = full_series[max(0, i-6): i+1]
        w_sum = sum(w["love_total"] for w in window)
        w_avg = round(w_sum / len(window), 2)
        moving.append({"date": pt["date"], "avg": w_avg})

    peaks = sorted(full_series, key=lambda x: x["love_total"], reverse=True)[:5]
    peaks = [p for p in peaks if p["love_total"] > 0][:3]

    # самые тёплые дни по люблю
    # также найдём день с максимумом любви
    return {
        "status": state["status"],
        "error": state["error"],
        "updated_at": payload()["updated_at"],
        "granularity": "day",
        "days": days,
        "range": {"from": full_series[0]["date"] if full_series else None, "to": full_series[-1]["date"] if full_series else None},
        "totals": totals,
        "average_per_day": avg,
        "average_active_day": avg_active,
        "max": max_v,
        "min": min_v,
        "series": full_series,
        "moving_avg_7": moving,
        "peaks": peaks,
        "is_demo": False,
        "tz": "Europe/Kyiv" if KYIV_TZ else "UTC",
        "dating": days_together_payload(),
    }


def _demo_series(days: int = 90) -> Dict[str, Any]:
    """Генерит красивую демо-серию для превью без реальных данных."""
    import random
    random.seed(42)
    if days == 0:
        days = 180
    end = date.today()
    start = end - timedelta(days=days - 1)
    series = []
    total_me = 0
    total_other = 0
    total_love_me = 0
    total_love_other = 0
    for i in range(days):
        cur = start + timedelta(days=i)
        ds = cur.isoformat()
        weekday = cur.weekday()
        base = 22 + random.randint(-6, 8)
        if weekday >= 5:
            base -= 4
        if i in (days - 22, days - 45, days - 67):
            tot = random.randint(0, 3)
        elif i in (days - 12, days - 33):
            tot = random.randint(2, 6)
        else:
            if random.random() < 0.07:
                tot = base + random.randint(15, 28)
            else:
                tot = max(0, base + random.randint(-5, 5))
        me = int(tot * (0.42 + random.random()*0.16))
        other = tot - me
        # любовь ~ 10-20% сообщений содержат люблю
        love_total = 0
        love_me = 0
        love_other = 0
        if tot > 0:
            # шанс что в этот день были люблю
            if random.random() < 0.92:
                love_total = max(0, int(tot * (0.08 + random.random()*0.12)) + random.randint(0, 2))
                # иногда 0
                if random.random() < 0.08:
                    love_total = 0
                love_me = int(love_total * (0.45 + random.random()*0.1))
                love_other = love_total - love_me
        total_me += me
        total_other += other
        total_love_me += love_me
        total_love_other += love_other
        series.append({"date": ds, "me": me, "other": other, "total": tot, "love_me": love_me, "love_other": love_other, "love_total": love_total})

    moving = []
    for i, pt in enumerate(series):
        window = series[max(0, i-6): i+1]
        w_sum = sum(w["total"] for w in window)
        moving.append({"date": pt["date"], "avg": round(w_sum/len(window),2)})

    avg = round(sum(s["total"] for s in series)/len(series),2) if series else 0
    avg_active = round(sum(s["total"] for s in series if s["total"]>0) / max(1, len([s for s in series if s["total"]>0])),2)
    max_v = max((s["total"] for s in series), default=0)
    min_v = min((s["total"] for s in series), default=0)
    base_ref = avg_active if avg_active else avg
    dips=[]
    for i, pt in enumerate(series):
        tot = pt["total"]
        ref = max(base_ref, moving[i]["avg"], 5)
        if (tot==0 and ref>=8) or (tot>0 and tot < ref*0.35 and ref>=7) or (tot>0 and tot<ref*0.5 and ref>=12 and tot<=6):
            severity = 1.0 if tot==0 else max(0,min(1,1-tot/ref))
            dips.append({"date": pt["date"], "total": tot, "me": pt["me"], "other": pt["other"], "ref_avg": round(ref,1), "diff": int(ref-tot), "severity": round(severity,2), "label": "тишина" if tot==0 else "просадка"})
    peaks = sorted(series, key=lambda x: x["total"], reverse=True)[:3]

    return {
        "status": "ok",
        "error": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "granularity": "day",
        "days": days,
        "range": {"from": series[0]["date"] if series else None, "to": series[-1]["date"] if series else None},
        "totals": {"me": total_me, "other": total_other, "total": total_me+total_other, "love_me": total_love_me, "love_other": total_love_other, "love_total": total_love_me+total_love_other},
        "average_per_day": avg,
        "average_active_day": avg_active,
        "max": max_v,
        "min": min_v,
        "series": series,
        "moving_avg_7": moving,
        "dips": dips,
        "peaks": peaks,
        "streaks": {"current_zero_streak": 0, "longest_zero_streak": 1},
        "is_demo": True,
        "tz": "Europe/Kyiv",
        "demo_note": "демо-данные для предпросмотра — реальные появятся после первой синхронизации Telegram",
        "dating": days_together_payload(),
    }


def _demo_love_series(days: int = 90) -> Dict[str, Any]:
    import random
    random.seed(123)
    if days == 0:
        days = 180
    end = date.today()
    start = end - timedelta(days=days - 1)
    series = []
    total_love_me = 0
    total_love_other = 0
    for i in range(days):
        cur = start + timedelta(days=i)
        ds = cur.isoformat()
        # любовь в день: 0-7, иногда всплеск 10+
        if random.random() < 0.18:
            love_total = 0
        elif random.random() < 0.07:
            love_total = random.randint(8, 14)
        else:
            love_total = random.randint(1, 6)
        # выходные чуть больше
        if cur.weekday() >= 5 and love_total > 0:
            love_total += random.randint(0, 2)
        love_me = int(love_total * (0.48 + random.random()*0.12))
        love_other = love_total - love_me
        total_love_me += love_me
        total_love_other += love_other
        series.append({"date": ds, "love_me": love_me, "love_other": love_other, "love_total": love_total})

    avg = round(sum(s["love_total"] for s in series)/len(series),2) if series else 0
    active = [s["love_total"] for s in series if s["love_total"]>0]
    avg_active = round(sum(active)/len(active),2) if active else 0
    max_v = max((s["love_total"] for s in series), default=0)
    min_v = min((s["love_total"] for s in series), default=0)
    moving = []
    for i, pt in enumerate(series):
        window = series[max(0, i-6): i+1]
        w_sum = sum(w["love_total"] for w in window)
        moving.append({"date": pt["date"], "avg": round(w_sum/len(window),2)})
    peaks = sorted(series, key=lambda x: x["love_total"], reverse=True)[:3]
    peaks = [p for p in peaks if p["love_total"]>0][:3]

    return {
        "status": "ok",
        "error": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "granularity": "day",
        "days": days,
        "range": {"from": series[0]["date"] if series else None, "to": series[-1]["date"] if series else None},
        "totals": {"love_me": total_love_me, "love_other": total_love_other, "love_total": total_love_me+total_love_other},
        "average_per_day": avg,
        "average_active_day": avg_active,
        "max": max_v,
        "min": min_v,
        "series": series,
        "moving_avg_7": moving,
        "peaks": peaks,
        "is_demo": True,
        "tz": "Europe/Kyiv",
        "dating": days_together_payload(),
        "demo_note": "демо-данные люблю — реальные после синхронизации",
    }


def stats_text() -> str:
    """Текст статистики для Telegram — как в исходном скрипте."""
    data = payload()
    me, other, total = data["me"]["messages"], data["other"]["messages"], data["total"]
    name = data["other"]["name"] or "Собеседник"
    line = "─" * 25
    # добавим люблю в текст если есть
    love_part = ""
    if data["love_total"] > 0:
        love_part = f"\n❤️ «Люблю»: я — {data['me']['love']}, {name} — {data['other']['love']} (всего {data['love_total']})"
    dating = days_together_payload()
    return (
        "📊 Статистика переписки\n"
        f"{line}\n"
        f"✉️ Я отправил: {me} сообщений\n"
        f"💬 {name} отправила: {other} сообщений\n"
        f"{line}\n"
        f"📨 Всего: {total} сообщений{love_part}\n\n"
        f"📅 Вместе: {dating['text']} (с {dating['start']})\n\n"
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
        if DEMO_MODE:
            state["status"] = "ok"
            state["error"] = None
            log.info("DEMO_MODE=1 — работаю без Telegram, отдаю демо-графики")
        else:
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
    # добавим dating для удобства
    data = payload()
    data["dating"] = days_together_payload()
    return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/series")
async def api_series(days: int = Query(90, ge=0, le=2000), refresh: int = 0, demo: int = 0):
    """
    Динамика по дням для графика просадок.
    days=0 — вся история, иначе последние N дней.
    demo=1 — принудительно вернуть демо-серию (для предпросмотра).
    """
    if demo:
        data = _demo_series(days if days else 90)
        return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})
    if refresh:
        state["updated_ts"] = 0
    # если DEMO_MODE и база пуста — сразу демо
    if DEMO_MODE and db_daily_count() == 0:
        data = _demo_series(days if days else 90)
        return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})
    await ensure_fresh()
    data = build_series(days)
    return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/history")
async def api_history(days: int = Query(90, ge=0, le=2000), refresh: int = 0, demo: int = 0):
    return await api_series(days=days, refresh=refresh, demo=demo)


@app.get("/api/love")
async def api_love(days: int = Query(90, ge=0, le=2000), refresh: int = 0, demo: int = 0):
    """
    Метрика «люблю»: сколько дней вместе, сколько сообщений с «люблю» и кто сколько.
    """
    if demo:
        data = _demo_love_series(days if days else 90)
        return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})
    if refresh:
        state["updated_ts"] = 0
    if DEMO_MODE and db_daily_count() == 0:
        data = _demo_love_series(days if days else 90)
        return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})
    await ensure_fresh()
    data = build_love_series(days)
    # добавим общие суммы люблю из state на случай если series пустая
    if not data["series"]:
        data["totals"] = {"love_me": state["love_me"], "love_other": state["love_other"], "love_total": state["love_me"]+state["love_other"]}
    # добавим проценты
    lt = data["totals"]["love_total"] if "love_total" in data["totals"] else 0
    lm = data["totals"]["love_me"] if "love_me" in data["totals"] else 0
    lo = data["totals"]["love_other"] if "love_other" in data["totals"] else 0
    data["love_percent"] = {"me": round(lm/lt*100,1) if lt else 0, "other": round(lo/lt*100,1) if lt else 0}
    data["me"] = {"name": MY_NAME, "love": lm}
    data["other"] = {"name": TARGET_NAME or state["title"] or "Собеседник", "love": lo}
    return JSONResponse(data, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/health")
async def health():
    return {
        "ok": state["status"] in ("ok", "syncing"),
        "status": state["status"],
        "error": state["error"],
        "updated_at": payload()["updated_at"],
        "total": state["me"] + state["other"],
        "love_total": state["love_me"] + state["love_other"],
        "daily_rows": db_daily_count(),
        "dating": days_together_payload(),
    }


@app.get("/")
async def root():
    return {
        "service": "статистика переписки",
        "stats": "/api/stats",
        "series": "/api/series?days=90  (график просадок)",
        "love": "/api/love?days=90  (сколько люблю + дни вместе)",
        "health": "/api/health",
        "status": state["status"],
    }
