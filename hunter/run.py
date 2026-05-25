"""Orchestrator: scrape -> dedup -> evaluate -> notify.

Usage:
  python -m hunter.run --config config.yaml
  python -m hunter.run --config config.yaml --skip-scrape   # only re-evaluate/notify
  python -m hunter.run --config config.yaml --skip-llm      # scrape only, no eval
  python -m hunter.run --config config.yaml --stats
"""
import argparse
import sys
import traceback
from pathlib import Path

import yaml

from .storage import Storage
from .scrapers.kleinanzeigen import KleinanzeigenScraper
from .scrapers.immowelt import ImmoweltScraper
from .scrapers.immoscout import ImmoscoutScraper
from .scrapers.rss import RssScraper
from .llm_filter import evaluate_listing
from .notifier import notify


SCRAPER_REGISTRY = {
    "kleinanzeigen": KleinanzeigenScraper,
    "immowelt": ImmoweltScraper,
    "immoscout24": ImmoscoutScraper,
    "rss": RssScraper,
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_scraping(config: dict, storage: Storage) -> tuple[int, int]:
    total_seen = 0
    total_new = 0
    for name, cfg in (config.get("scrapers") or {}).items():
        if not cfg.get("enabled"):
            continue
        cls = SCRAPER_REGISTRY.get(name)
        if not cls:
            print(f"[run] unknown scraper '{name}', skipping")
            continue
        scraper = cls()
        print(f"\n[run] === {name} ===")
        for search in cfg.get("searches") or []:
            try:
                for listing in scraper.fetch(search):
                    total_seen += 1
                    if storage.upsert(listing):
                        total_new += 1
                        print(
                            f"  + NEW {listing.uid} | {listing.price_eur or '?'} € | "
                            f"{listing.sqm or '?'} m² | {listing.location[:30]} | {listing.title[:50]}"
                        )
            except Exception as e:
                print(f"[run/{name}] error: {e}")
                traceback.print_exc()
    return total_seen, total_new


def run_llm(config: dict, storage: Storage) -> int:
    rows = storage.unevaluated(limit=config.get("llm_max_per_run", 40))
    if not rows:
        print("[llm] nothing to evaluate")
        return 0
    print(f"\n[llm] evaluating {len(rows)} listings")
    model = config.get("llm_model", "claude-sonnet-4-6")
    backend = config.get("llm_backend", "cli")
    evaluated = 0
    for row in rows:
        try:
            result = evaluate_listing(row, model=model, backend=backend)
            storage.save_evaluation(
                row["uid"],
                result["score"],
                result["reasoning"],
                result["red_flags"],
            )
            evaluated += 1
            print(
                f"  · {row['uid']:<45} score={result['score']:>2}  "
                f"{result['reasoning'][:70]}"
            )
        except Exception as e:
            print(f"  ! {row['uid']} llm error: {e}")
    return evaluated


def run_notify(config: dict, storage: Storage) -> int:
    threshold = config.get("notify_threshold", 7)
    rows = storage.pending_notification(threshold)
    if not rows:
        print(f"[notify] no listings >= {threshold}")
        return 0
    print(f"\n[notify] {len(rows)} listings to push (threshold {threshold})")
    sent = 0
    for row in rows:
        if notify(row, config):
            storage.mark_notified(row["uid"])
            sent += 1
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--skip-notify", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).parent / cfg_path
    config = load_config(str(cfg_path))

    db_path = config.get("db_path", "../data/listings.db")
    if not Path(db_path).is_absolute():
        db_path = str(Path(__file__).parent / db_path)
    storage = Storage(db_path)

    if args.stats:
        import json as _json
        print(_json.dumps(storage.stats(), indent=2))
        return

    if not args.skip_scrape:
        seen, new = run_scraping(config, storage)
        print(f"\n[summary/scrape] seen={seen} new={new}")
    if not args.skip_llm:
        ev = run_llm(config, storage)
        print(f"[summary/llm] evaluated={ev}")
    if not args.skip_notify:
        sent = run_notify(config, storage)
        print(f"[summary/notify] sent={sent}")

    storage.close()


if __name__ == "__main__":
    main()
