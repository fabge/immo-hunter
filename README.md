# immo-hunter

Automated house-hunting for the Heidelberg corridor (Fabian & Sarah).

Two parallel tracks:
- **`hunter/`** — own implementation: stdlib + Playwright scrapers, SQLite dedup, Claude LLM filter, Telegram push. Full control over filtering.
- **`flathunter/`** — setup notes for the [flathunter](https://github.com/flathunters/flathunter) OSS tool as alternative/backup for comparison.

Background and strategy: `/Users/fabian/code/notes/personal/where-to-live/house-hunting.md`

## Quickstart (own stack)

```bash
cd /Users/fabian/code/fabge/immo-hunter
pip install -r hunter/requirements.txt

# Optional, only if enabling immowelt/immoscout scrapers:
pip install playwright && playwright install chromium

cp hunter/config.example.yaml hunter/config.yaml
# edit hunter/config.yaml: enable scrapers, tweak budget/region

cp .env.example .env
# fill in telegram creds (.env is gitignored; config.yaml is tracked and holds no secrets)

python -m hunter.run --config config.yaml
```

CLI flags:
- `--skip-scrape` — only re-evaluate + notify (useful after tweaking the LLM prompt)
- `--skip-llm` — only scrape (useful for first-time discovery without LLM cost)
- `--skip-notify` — eval but don't push
- `--stats` — print per-source listing counts
- `--loop` — run forever, sleeping `RUN_INTERVAL_MINUTES` (default 30) between runs; Docker mode

## Architecture

```
hunter/
├── models.py            Listing dataclass
├── storage.py           SQLite; dedup by uid, change detection via content_hash
├── scrapers/
│   ├── base.py
│   ├── kleinanzeigen.py    stdlib HTTP, works out of the box
│   ├── immowelt.py         Playwright (blocked by DataDome, disabled)
│   ├── immoscout.py        IS24 mobile-app API (stdlib, incl. expose details)
│   └── rss.py              Immoscout24 Sparalarm feeds
├── llm_filter.py        Claude scoring (CLI or API backend)
├── notifier.py          Telegram (HTML) + console fallback + ops alerts
└── run.py               Orchestrator CLI
tests/                   Parser/storage fixture tests: python -m unittest discover -s tests
```

Pipeline behaviors worth knowing:
- A changed listing (e.g. **price drop**) is detected via content hash, re-scored, and re-pushed.
- IS24 listings get their **expose description fetched** at evaluation time (the list API has none).
- An enabled scraper yielding **0 listings triggers a Telegram alert** (likely parser breakage).
- A failed Telegram push stays pending and is **retried next run**; the same house seen on two portals is only pushed once.

## LLM backend

Three backends, selectable via `llm_backend` in config — or the `LLM_BACKEND` /
`LLM_MODEL` / `LLM_BASE_URL` env vars, which override config so the tracked
config.yaml stays host-neutral:

- `cli` (Mac default) — `claude -p` CLI, free at point of use on the Max subscription.
- `api` — anthropic SDK with `ANTHROPIC_API_KEY`.
- `openai` — any OpenAI-compatible `/chat/completions` endpoint, stdlib only:
  OpenCode Zen (`https://opencode.ai/zen/v1`, models like `glm-5.1`, `kimi-k2.5`,
  `deepseek-v4-pro`), a LiteLLM proxy, OpenRouter, or local Ollama. Key goes in
  the `LLM_API_KEY` env var. This is what the Docker deployment uses.

`llm_model` / `LLM_MODEL` accepts a **fallback chain** (comma-separated, primary
first): `LLM_MODEL=deepseek-v4-flash-free,glm-5.1` runs Zen's free model and
falls back to the paid one when it errors or rate-limits. A model that fails
twice in a run is skipped for the rest of that run; if all models fail, the
remaining listings stay unevaluated and are retried next cycle.

## Telegram setup

1. Open Telegram, message [@BotFather](https://t.me/botfather), `/newbot`, follow prompts → get bot token.
2. Start a chat with your new bot, send any message.
3. Get your chat ID: `curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[0].message.chat.id'`
4. Put both in `.env` at the repo root as `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (see `.env.example`). Loaded by `run.py` itself, so it works under launchd too.

Console fallback works when telegram creds are missing — useful for dev.

## Deployment: Docker on terra (primary)

Long-running container, scraping every 30 min. Service is defined in
`setup/terra/docker-compose.yml` following the `pa` pattern: image built from
the repo, repo bind-mounted over `/app` so config edits and the SQLite DB
(`data/listings.db`) live on the host and survive rebuilds.

On terra:

```bash
git clone git@github.com:fabge/immo-hunter.git ~/config/immo-hunter
# add IMMO_TELEGRAM_BOT_TOKEN, IMMO_TELEGRAM_CHAT_ID, OPENCODE_API_KEY to ~/.env
docker compose up -d --build immo-hunter
docker logs -f immo-hunter
```

LLM config is injected via env (`LLM_BACKEND=openai`, OpenCode Zen base URL,
`LLM_MODEL=glm-5.1`) — swap models/providers by editing the compose env, no
code or config.yaml change. Update flow: `cd ~/config/immo-hunter && git pull`,
then `docker compose up -d --build immo-hunter` (rebuild only needed when
requirements.txt changes; a restart picks up code changes since the repo is
bind-mounted).

## Scheduling (alternative: launchd on Mac)

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
  <key>WorkingDirectory</key><string>/Users/fabian/code/fabge/immo-hunter</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardOutPath</key><string>/Users/fabian/code/fabge/immo-hunter/logs/run.log</string>
  <key>StandardErrorPath</key><string>/Users/fabian/code/fabge/immo-hunter/logs/run.err.log</string>
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
- [x] IS24 expose-detail fetch (description/Lage/Ausstattung for LLM scoring)
- [x] Price-drop detection + re-notify (content_hash)
- [x] Zero-result scraper alerts (parser-breakage detection)
- [x] Parser/storage test suite (`python -m unittest discover -s tests`)
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
