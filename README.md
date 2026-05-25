# immo-hunter

Automated house-hunting for the Heidelberg corridor (Fabian & Sarah).

Two parallel tracks:
- **`hunter/`** — own implementation: stdlib + Playwright scrapers, SQLite dedup, Claude LLM filter, Telegram push. Full control over filtering.
- **`flathunter/`** — setup notes for the [flathunter](https://github.com/flathunters/flathunter) OSS tool as alternative/backup for comparison.

Background and strategy: `/Users/fabian/code/notes/personal/where-to-live/house-hunting.md`

## Quickstart (own stack)

```bash
cd /Users/fabian/code/immo-hunter
pip install -r hunter/requirements.txt

# Optional, only if enabling immowelt/immoscout scrapers:
pip install playwright && playwright install chromium

cp hunter/config.example.yaml hunter/config.yaml
# edit hunter/config.yaml: enable scrapers, set telegram creds, tweak budget/region

python -m hunter.run --config config.yaml
```

CLI flags:
- `--skip-scrape` — only re-evaluate + notify (useful after tweaking the LLM prompt)
- `--skip-llm` — only scrape (useful for first-time discovery without LLM cost)
- `--skip-notify` — eval but don't push
- `--stats` — print per-source listing counts

## Architecture

```
hunter/
├── models.py            Listing dataclass
├── storage.py           SQLite, dedup by uid (source:source_id)
├── scrapers/
│   ├── base.py
│   ├── kleinanzeigen.py    stdlib HTTP, works out of the box
│   ├── immowelt.py         Playwright (heavy bot detection)
│   ├── immoscout.py        Playwright (heavy bot detection)
│   └── rss.py              Immoscout24 Sparalarm feeds
├── llm_filter.py        Claude scoring (CLI or API backend)
├── notifier.py          Telegram + console fallback
└── run.py               Orchestrator CLI
```

## LLM backend

Default uses the `claude -p` CLI (Max subscription, free at point of use). The runner strips `ANTHROPIC_API_KEY` from the subprocess environment so the CLI falls back to its OAuth credentials.

Switch to direct API by setting `llm_backend: api` in config and providing a valid `ANTHROPIC_API_KEY`.

## Telegram setup

1. Open Telegram, message [@BotFather](https://t.me/botfather), `/newbot`, follow prompts → get bot token.
2. Start a chat with your new bot, send any message.
3. Get your chat ID: `curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[0].message.chat.id'`
4. Put both in `config.yaml` under `telegram:` or export as `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.

Console fallback works when telegram creds are missing — useful for dev.

## Scheduling

Local launchd plist (runs every 30 min when Mac is awake):

```xml
<!-- ~/Library/LaunchAgents/com.fabian.immohunter.plist -->
<plist version="1.0">
<dict>
  <key>Label</key><string>com.fabian.immohunter</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>-m</string>
    <string>hunter.run</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/fabian/code/immo-hunter</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardOutPath</key><string>/Users/fabian/code/immo-hunter/logs/run.log</string>
  <key>StandardErrorPath</key><string>/Users/fabian/code/immo-hunter/logs/run.err.log</string>
</dict>
</plist>
```

Load: `launchctl load ~/Library/LaunchAgents/com.fabian.immohunter.plist`

## Current status

- [x] Kleinanzeigen scraper (stdlib, works)
- [x] SQLite storage + dedup
- [x] LLM filter (CLI backend)
- [x] Telegram + console notifier
- [x] Orchestrator CLI
- [ ] Immowelt scraper (code written, needs `playwright install` + selector tuning against live HTML)
- [ ] Immoscout24 scraper (code written, needs `playwright install` + cookie banner / captcha handling)
- [ ] RSS feed for Immoscout Sparalarm (code written, needs user to paste actual feed URL)
- [ ] Bausachverständigen-Liste integration (manual lookup, not automated)

## Comparing with flathunter

See `flathunter/README.md` for setup. Run both side by side, compare hit rates and false-positive rates over a month, decide which gives better Score-7+ signal.
