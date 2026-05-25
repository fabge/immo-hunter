"""Notification sinks: Telegram (primary) + console fallback."""
import os
import sqlite3
import urllib.request
import urllib.parse
import json


def format_listing(row: sqlite3.Row) -> str:
    ppsqm = (
        f"{row['price_eur'] / row['sqm']:.0f} €/m²"
        if row["price_eur"] and row["sqm"]
        else "n/a"
    )
    return (
        f"🏠 *Score {row['llm_score']}/10* — {row['source']}\n"
        f"*{row['title']}*\n"
        f"💶 {row['price_eur'] or 'n/a'} € | 📐 {row['sqm'] or 'n/a'} m² | {ppsqm}\n"
        f"📍 {row['location'] or 'n/a'}\n\n"
        f"_{row['llm_reasoning']}_\n"
        f"{('⚠️ ' + row['llm_red_flags']) if row['llm_red_flags'] else ''}\n\n"
        f"{row['url']}"
    )


def send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": "false",
        }
    ).encode()
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"[telegram] {e}")
        return False


def notify(row: sqlite3.Row, config: dict) -> bool:
    text = format_listing(row)
    telegram = config.get("telegram") or {}
    bot_token = telegram.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = telegram.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        if send_telegram(text, bot_token, chat_id):
            return True
    # Fallback: console
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)
    return True
