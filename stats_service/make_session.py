#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор TG_SESSION (Telethon StringSession).

Запускать ОДИН РАЗ на своём компьютере:

    pip install telethon
    python make_session.py

Скрипт спросит номер телефона, код из Telegram и пароль 2FA (если включён),
затем напечатает длинную строку — это и есть TG_SESSION.
Строку нужно вставить в Render → сервис статистики → Environment → TG_SESSION.

⚠️ Строка TG_SESSION = полный доступ к твоему аккаунту Telegram.
   Никому её не показывай, не коммить в GitHub, не пересылай в чатах.
   Если она утекла — Telegram → Настройки → Устройства → завершить сеанс,
   и/или создай новый app на my.telegram.org.
"""

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("API_ID") or input("API_ID (с my.telegram.org): ").strip())
API_HASH = os.getenv("API_HASH") or input("API_HASH (с my.telegram.org): ").strip()


async def main() -> None:
    print("\nПодключаюсь к Telegram…\n")
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        me = await client.get_me()
        session = client.session.save()
        print("=" * 70)
        print(f"Авторизован как: {me.first_name} (@{me.username}) id={me.id}")
        print("=" * 70)
        print("\nTG_SESSION (скопируй целиком одной строкой):\n")
        print(session)
        print("\n" + "=" * 70)
        print("Куда вставить: Render → love-stats → Environment → Add Environment Variable")
        print("  key:   TG_SESSION")
        print("  value: (строка выше)")
        print("=" * 70)

        # удобно: сразу сохранить в .env для локального запуска (в git не коммитить!)
        with open(".env", "w", encoding="utf-8") as f:
            f.write(f"API_ID={API_ID}\nAPI_HASH={API_HASH}\nTG_SESSION={session}\n")
        print("\nЛокально сохранил в .env (файл не должен попадать в git).")


if __name__ == "__main__":
    asyncio.run(main())
