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

Default uses the `claude -p` CLI (Max subscription, free at point of use).

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

- [x] Kleinanzeigen scraper (stdlib, no browser, works — ~27/search in 20km radius)
- [x] **Immoscout24 scraper via mobile-app API** (stdlib, no captcha, works — 1720 total hits, paginated)
- [x] SQLite storage + dedup
- [x] LLM filter (CLI backend, correctly rejects Mannheim/Bauträger/out-of-corridor)
- [x] Telegram + console notifier
- [x] Orchestrator CLI
- [x] RSS reader for Immoscout Sparalarm (needs user to paste actual feed URL to enable)
- [ ] Immowelt scraper — **blocked by DataDome on web + API**; needs undetected-chromedriver + cookie solving. Low priority (inventory overlaps IS24). Playwright code present but disabled.
- [ ] Telegram bot setup (deferred)
- [ ] launchd schedule (deferred)
- [ ] Bausachverständigen-Liste integration (manual lookup, not automated)

### Anti-bot reality (tested 2026-05-25)

- **Kleinanzeigen**: plain HTTP works.
- **Immoscout24 website**: serves DataDome "Ich bin kein Roboter" captcha to headless + stealth + headed Chromium. Not scrapable. **But** the mobile-app API (`api.mobile.immobilienscout24.de`) has no captcha — that's what we use.
- **Immowelt**: DataDome on both web and backend API endpoints. No clean path.

## Comparing with flathunter

See `flathunter/README.md` for setup. Run both side by side, compare hit rates and false-positive rates over a month, decide which gives better Score-7+ signal.
