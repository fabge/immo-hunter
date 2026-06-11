"""Notification sinks: Telegram (primary) + console fallback.

Uses Telegram HTML parse mode: legacy Markdown breaks on unescaped *_[ in
listing titles, which would 400 the send.
"""
import html
import os
import urllib.request
import urllib.parse
import json


def _esc(v) -> str:
    return html.escape(str(v), quote=False)


def format_listing(row) -> str:
    ppsqm = (
        f"{row['price_eur'] / row['sqm']:.0f} €/m²"
        if row["price_eur"] and row["sqm"]
        else "n/a"
    )
    red_flags = f"⚠️ {_esc(row['llm_red_flags'])}\n\n" if row["llm_red_flags"] else "\n"
    return (
        f"🏠 <b>Score {row['llm_score']}/10</b> — {_esc(row['source'])}\n"
        f"<b>{_esc(row['title'])}</b>\n"
        f"💶 {row['price_eur'] or 'n/a'} € | 📐 {row['sqm'] or 'n/a'} m² | {ppsqm}\n"
        f"📍 {_esc(row['location'] or 'n/a')}\n\n"
        f"<i>{_esc(row['llm_reasoning'])}</i>\n"
        f"{red_flags}"
        f"{row['url']}"
    )


def _telegram_creds(config: dict):
    # Env-only (populated from .env by run.load_dotenv); config.yaml is
    # tracked in git and must not hold secrets.
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
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


def _print_console(text: str):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def notify(row, config: dict) -> bool:
    """Push one listing. Returns True only if actually delivered.

    With telegram creds configured, a failed send returns False so the
    listing stays pending and is retried next run. Console fallback counts
    as delivered only in dev mode (no creds configured).
    """
    text = format_listing(row)
    bot_token, chat_id = _telegram_creds(config)
    if bot_token and chat_id:
        return send_telegram(text, bot_token, chat_id)
    _print_console(text)
    return True


def send_alert(text: str, config: dict):
    """Operational warning (e.g. a scraper returned zero results). Best effort."""
    bot_token, chat_id = _telegram_creds(config)
    if bot_token and chat_id:
        if send_telegram(_esc(text), bot_token, chat_id):
            return
    _print_console(text)
