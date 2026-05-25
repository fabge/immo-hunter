# flathunter — alternative/backup track

[flathunter](https://github.com/flathunters/flathunter) is a well-maintained OSS hunter (originally for rentals, but supports Kauf with `crawl_paths` config). Used here as a comparison baseline against our own `hunter/` stack.

## Setup

```bash
cd /Users/fabian/code/immo-hunter/flathunter
git clone https://github.com/flathunters/flathunter.git src
cd src
pip install pipenv
pipenv install
cp config.yaml.dist ../config.yaml
# edit ../config.yaml:
#  - urls: paste your Immoscout24 / Immowelt / Kleinanzeigen search URLs
#  - telegram: bot token + chat id
#  - filters: price, sqm, etc.
pipenv run python flathunt.py --config ../config.yaml
```

For continuous mode add `--heartbeat hourly` and run via cron / launchd.

## URLs to use

Paste fully-configured search URLs (with all filters in the query string):

- Immoscout: `https://www.immobilienscout24.de/Suche/de/baden-wuerttemberg/heidelberg-kreisfreie-stadt/haus-kaufen?price=-800000&livingspace=100-`
- Immowelt: from the search results page after applying filters
- Kleinanzeigen: `https://www.kleinanzeigen.de/s-haus-kaufen/heidelberg/c208l9166r20` (l9166 = Heidelberg, r20 = 20km radius)

flathunter handles polling + dedup + Telegram push out of the box. It does **not** do LLM filtering — that's our `hunter/` differentiator.

## Test results (2026-05-25)

Cloned + ran flathunter's crawlers directly against the HD corridor:

| Crawler | Result | Notes |
|---------|--------|-------|
| **Kleinanzeigen** | ✓ 27 results | Works, but launches undetected-chromedriver (real headless Chrome) where our stdlib scraper needs no browser |
| **Immobilienscout24** | ✗ `KeyError: 'totalResults'` | flathunter's mobile-API crawler is **stale against the current API response** (now nests paging under `paging.numberOfPages`, no top-level `totalResults`). Our `hunter/scrapers/immoscout.py` reimplements the same endpoint with defensive parsing and works. |
| **Immowelt** | not run | Behind DataDome on web + API; flathunter relies on undetected-chromedriver, fragile |

**Key insight borrowed:** flathunter's IS24 crawler revealed the mobile-app API
(`api.mobile.immobilienscout24.de/search/list`, UA `ImmoScout_27.3_26.0_._`) which
bypasses the website's DataDome captcha entirely. We adopted this in our own stack.

Runtime deps: `pip install pyyaml requests lxml beautifulsoup4 selenium undetected-chromedriver
webdriver-manager apprise jsonpath-ng backoff requests-random-user-agent ruamel.yaml prompt-toolkit`.
The full `flathunt.py` loop also requires a configured notifier (telegram/apprise) or it raises
`HeartbeatException`.

## Comparison strategy

Run both in parallel for ~4 weeks:
- flathunter pushes raw matches → high recall, lower precision, no LLM filter
- our `hunter/` pushes Score-7+ matches → lower recall, higher precision

Compare:
- Total notifications per week
- Genuine "worth a closer look" hit rate
- False positives (Bauträger spam, out-of-corridor, etc.)
- Latency from listing publication → notification

Current verdict: our stack is lighter (no Chrome for Kleinanzeigen + IS24) and the LLM
filter kills the Bauträger/Mannheim noise that flathunter would forward raw. Keep
flathunter as a cross-check baseline.
