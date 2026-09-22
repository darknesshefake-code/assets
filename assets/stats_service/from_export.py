#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запасной вариант: считает сообщения из выгрузки Telegram Desktop и делает
файл love_site/stats.json, который страница «Статистика» покажет,
даже если сервис с Telegram не работает.

Как получить выгрузку:
  Telegram Desktop → нужный чат → ⋮ (меню чата) → Export chat history
  → снять галочки с фото/видео (нужен только текст) → Format: JSON
  → получится папка с файлом result.json

Запуск:
  python from_export.py путь/к/result.json
  python from_export.py result.json --her "Аня" --me "Я" --out ../love_site/stats.json

Поддерживается и HTML-выгрузка (messages.html / messages2.html) — тогда просто
укажите её путь вместо result.json.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

ISO = "%Y-%m-%dT%H:%M:%S"


def parse_date(value) -> str:
    """Приводит дату из выгрузки к ISO-8601 (UTC), как отдаёт сервис."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None).isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc).replace(tzinfo=None).isoformat()
        except ValueError:
            continue
    return None


def from_json(path: str, me_name: str, her_name: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages") or []
    me = other = 0
    first_at = last_at = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") not in (None, "message"):
            continue                                   # служебные («присоединился», «изменил имя»)
        if msg.get("text") in ("", None) and not msg.get("media_type"):   # пустышки без контента
            if not msg.get("photo") and not msg.get("file"):
                continue

        if msg.get("out"):
            me += 1
        else:
            other += 1

        stamp = parse_date(msg.get("date"))
        if stamp:
            first_at = stamp if first_at is None or stamp < first_at else first_at
            last_at = stamp if last_at is None or stamp > last_at else last_at

    return {
        "chat_title": data.get("name") or her_name,
        "me": me,
        "other": other,
        "first_message_at": first_at,
        "last_message_at": last_at,
    }


def from_html(path: str, me_name: str, her_name: str) -> dict:
    html = open(path, encoding="utf-8", errors="ignore").read()

    # каждый обычный блок сообщения: <div class="message default clearfix" ...>
    blocks = re.findall(
        r'<div class="message default clearfix([^"]*)"[\s\S]*?(?=<div class="message |\Z)',
        html)

    me = other = 0
    first_at = last_at = None
    date_re = re.compile(r'title="(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})"')

    for block in re.finditer(
        r'<div class="message default clearfix([^"]*)"[\s\S]*?(?=<div class="message |\Z)', html):
        cls, body = block.group(1), block.group(0)
        if " out" in " " + cls.strip() + " " or cls.strip() == "out":
            me += 1
        else:
            other += 1
        found = date_re.search(body)
        if found:
            stamp = parse_date(found.group(1))
            if stamp:
                first_at = stamp if first_at is None or stamp < first_at else first_at
                last_at = stamp if last_at is None or stamp > last_at else last_at

    title = re.search(r"<div class=\"text bold\">\s*([^<]+?)\s*</div>", html)
    return {
        "chat_title": (title.group(1) if title else her_name),
        "me": me,
        "other": other,
        "first_message_at": first_at,
        "last_message_at": last_at,
    }


def build_stats(path: str, me_name: str, her_name: str) -> dict:
    if path.lower().endswith(".json"):
        raw = from_json(path, me_name, her_name)
    else:
        raw = from_html(path, me_name, her_name)

    me, other = raw["me"], raw["other"]
    total = me + other
    her_title = raw.get("chat_title") or her_name

    return {
        "status": "static",
        "source": "telegram-export",
        "chat": {"title": her_title, "phone": None},
        "me": {"name": me_name, "messages": me, "percent": round(me / total * 100, 1) if total else 0.0},
        "other": {"name": her_title, "messages": other, "percent": round(other / total * 100, 1) if total else 0.0},
        "total": total,
        "first_message_at": raw["first_message_at"],
        "last_message_at": raw["last_message_at"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(here, "..", "love_site", "stats.json")

    ap = argparse.ArgumentParser(description="Выгрузка Telegram → stats.json для сайта")
    ap.add_argument("export", help="result.json или messages.html из выгрузки Telegram Desktop")
    ap.add_argument("--out", default=os.path.normpath(default_out), help="куда сохранить stats.json")
    ap.add_argument("--me", default="Я", help="как подписывать меня")
    ap.add_argument("--her", default="Собеседник", help="как подписывать её")
    args = ap.parse_args()

    if not os.path.exists(args.export):
        print(f"❌ Файл не найден: {args.export}")
        return 1

    stats = build_stats(args.export, args.me, args.her)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("=" * 46)
    print(f"💬 Диалог:            {stats['chat']['title']}")
    print(f"✉️  Я отправил:        {stats['me']['messages']} ({stats['me']['percent']}%)")
    print(f"💌 Она отправила:     {stats['other']['messages']} ({stats['other']['percent']}%)")
    print(f"📨 Всего:             {stats['total']}")
    print(f"📅 Первое сообщение:  {stats['first_message_at']}")
    print("=" * 46)
    print(f"✅ Сохранил: {args.out}")
    print("   Теперь закоммить папку love_site — страница «Статистика» покажет эти цифры,")
    print("   даже когда сервис с Telegram спит или ещё не настроен.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
