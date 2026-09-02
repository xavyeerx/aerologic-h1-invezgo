#!/usr/bin/env python3
"""
Bantu temukan message_thread_id tiap topik forum Telegram.

CARA PAKAI:
  1. Di grup Telegram (Topics aktif), kirim 1 pesan pendek di TIAP topik yang mau
     dipakai bot (mis. ketik "id" di topik Insight, IDX Info, Algobot, dst).
  2. Jalankan:  python scripts/find_topic_ids.py
  3. Salin thread_id yang muncul ke TELEGRAM_SCANNER_TOPIC_ID di .env.

Catatan: Telegram getUpdates hanya menyimpan update ~24 jam & akan kosong bila
webhook aktif atau update sudah dikonsumsi. Kirim pesan tepat sebelum menjalankan.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    print("TELEGRAM_BOT_TOKEN belum diset di .env")
    sys.exit(1)


def main() -> None:
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15)
    data = r.json()
    if not data.get("ok"):
        print("Gagal getUpdates:", data)
        return

    updates = data.get("result", [])
    if not updates:
        print("Tidak ada update. Kirim dulu 1 pesan di tiap topik lalu jalankan lagi.")
        print("(Jika bot pakai webhook, getUpdates memang kosong — matikan webhook dulu.)")
        return

    found: dict[int, str] = {}
    chat_id = None
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat", {})
        if chat.get("id"):
            chat_id = chat["id"]
        tid = msg.get("message_thread_id")
        if tid is None:
            continue
        # Nama topik bisa muncul di forum_topic_created (pesan pembuatan topik)
        name = (
            msg.get("forum_topic_created", {}).get("name")
            or msg.get("reply_to_message", {}).get("forum_topic_created", {}).get("name")
            or found.get(tid)
            or f"(topik {tid})"
        )
        found[tid] = name

    print(f"Chat ID grup: {chat_id}")
    print("=" * 40)
    if not found:
        print("Tidak ada message_thread_id terdeteksi.")
        print("Pastikan grup pakai Topics & pesan dikirim DI DALAM topik (bukan General).")
        return

    print("thread_id : nama topik")
    for tid, name in sorted(found.items()):
        print(f"  {tid} : {name}")
    print("=" * 40)
    print("Salin thread_id yang relevan ke .env, contoh:")
    print("  TELEGRAM_SCANNER_TOPIC_ID=<thread_id topik scanner>")


if __name__ == "__main__":
    main()
