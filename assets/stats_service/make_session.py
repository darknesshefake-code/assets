#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор TG_SESSION (Telethon StringSession) для сервиса статистики.

Запуск (один раз, на своём компьютере или в Google Colab):

    pip install telethon
    python make_session.py

Проверить уже имеющуюся строку:

    python make_session.py --check "строка_сессии"

⚠️ ВАЖНО: нужен вход НОМЕРОМ ТЕЛЕФОНА твоего обычного аккаунта.
   Сессия БОТА (полученная по бот-токену от @BotFather) НЕ ПОДХОДИТ:
   Telegram запрещает ботам читать историю чатов и список диалогов
   (ошибка BotMethodInvalidError: GetDialogsRequest / GetHistoryRequest).
   Скрипт предупредит, если ты случайно вошёл как бот.

⚠️ Строка TG_SESSION = полный доступ к аккаунту Telegram.
   Не публикуй её, не коммить в GitHub, не пересылай в чатах.
   Утекла — Telegram → Настройки → Устройства → завершить сеанс,
   и/или создай новое приложение на my.telegram.org.
"""

import argparse
import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

BOT_WARNING = """
╔══════════════════════════════════════════════════════════════════════╗
║  ЭТО СЕССИЯ БОТА — ДЛЯ САЙТА ОНА НЕ ПОДОЙДЁТ                        ║
╚══════════════════════════════════════════════════════════════════════╝
Telegram запрещает ботам читать историю чатов и список диалогов:
такая сессия упадёт с BotMethodInvalidError (GetDialogs / GetHistory).

Что делать: запусти этот скрипт заново и войди НОМЕРОМ ТЕЛЕФОНА своего
обычного аккаунта — того, в котором есть переписка. Код придёт в приложение
Telegram (не по SMS), а если включён облачный пароль — понадобится и он.

Бот-токен вставлять не нужно нигде: ни здесь, ни в Render.
"""


async def check(session: str, api_id: int = 0, api_hash: str = "") -> int:
    """Проверяет строку сессии: жива ли и не бот ли это."""
    api_id = api_id or int(os.getenv("API_ID") or 0)
    api_hash = api_hash or os.getenv("API_HASH") or ""
    if not (api_id and api_hash):
        print("Нужны API_ID и API_HASH (свои или в переменных окружения).")
        return 1

    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        me = await client.get_me()
        if me is None:
            print("❌ Сессия недействительна — сгенерируй новую.")
            return 1
        print(f"Аккаунт: {me.first_name} (@{me.username}) id={me.id}")
        if getattr(me, "bot", False):
            print(BOT_WARNING)
            return 2
        print("✅ Это сессия обычного аккаунта — для сервиса статистики подходит.")
        try:
            n = 0
            async for _ in client.iter_dialogs(limit=50):
                n += 1
            print(f"✅ Чтение диалогов работает (проверил {n} чатов).")
        except Exception as exc:
            print(f"⚠️ Диалоги не читаются: {exc}")
        return 0


async def main(args) -> int:
    await asyncio.sleep(0)
    api_id = args.api_id or int(os.getenv("API_ID") or input("API_ID (с my.telegram.org): ").strip())
    api_hash = args.api_hash or os.getenv("API_HASH") or input("API_HASH (с my.telegram.org): ").strip()

    print("\nВход в аккаунт. Telethon спросит номер телефона и код из Telegram.")
    print("Номер вводи в международном формате: +380...\n")

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        session = client.session.save()

        if me is None:
            print("❌ Не удалось авторизоваться.")
            return 1

        print("=" * 70)
        print(f"Авторизован как: {me.first_name} (@{me.username}) id={me.id}")
        print("=" * 70)

        if getattr(me, "bot", False):
            print(BOT_WARNING)
            return 2                                   # строку не показываем: она бесполезна

        print("\nTG_SESSION (скопируй целиком одной строкой):\n")
        print(session)
        print("\n" + "=" * 70)
        print("Куда вставить: Render → сервис статистики → Environment → Add Environment Variable")
        print("  key:   TG_SESSION")
        print("  value: (строка выше)")
        print("=" * 70)

        with open(".env", "w", encoding="utf-8") as f:
            f.write(f"API_ID={api_id}\nAPI_HASH={api_hash}\nTG_SESSION={session}\n")
        print("\nЛокально сохранил в .env (файл не должен попадать в git — он в .gitignore).")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Генератор TG_SESSION для сервиса статистики")
    ap.add_argument("--check", metavar="SESSION", help="проверить имеющуюся строку сессии")
    ap.add_argument("--api-id", type=int, default=0, help="api_id (иначе спросит)")
    ap.add_argument("--api-hash", default="", help="api_hash (иначе спросит)")
    a = ap.parse_args()

    try:
        if a.check:
            sys.exit(asyncio.run(check(a.check, a.api_id, a.api_hash)))
        sys.exit(asyncio.run(main(a)))
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(130)
