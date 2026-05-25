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

## Comparison strategy

Run both in parallel for ~4 weeks:
- flathunter pushes raw matches → high recall, lower precision
- our `hunter/` pushes Score-7+ matches → lower recall, higher precision

Compare:
- Total notifications per week
- Genuine "worth a closer look" hit rate
- False positives (Bauträger spam, out-of-corridor, etc.)
- Latency from listing publication → notification
