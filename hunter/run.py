"""Orchestrator: scrape -> dedup -> evaluate -> notify.

Usage:
  python -m hunter.run --config config.yaml
  python -m hunter.run --config config.yaml --skip-scrape   # only re-evaluate/notify
  python -m hunter.run --config config.yaml --skip-llm      # scrape only, no eval
  python -m hunter.run --config config.yaml --stats
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

import yaml

from .storage import Storage
from .scrapers.kleinanzeigen import KleinanzeigenScraper
from .scrapers.immowelt import ImmoweltScraper
from .scrapers.immoscout import ImmoscoutScraper, fetch_expose_description
from .scrapers.rss import RssScraper
from .llm_filter import evaluate_listing, ModelChain
from .notifier import notify, send_alert


SCRAPER_REGISTRY = {
    "kleinanzeigen": KleinanzeigenScraper,
    "immowelt": ImmoweltScraper,
    "immoscout24": ImmoscoutScraper,
    "rss": RssScraper,
}


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_dotenv():
    """Load KEY=VALUE pairs from the repo-root .env into os.environ.

    Needed because launchd doesn't source the shell profile. Existing env
    vars win over .env values.
    """
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value:
            os.environ.setdefault(key, value)


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
        scraper_seen = 0
        for search in cfg.get("searches") or []:
            try:
                for listing in scraper.fetch(search):
                    scraper_seen += 1
                    status = storage.upsert(listing)
                    if status != "seen":
                        total_new += 1
                        print(
                            f"  + {status.upper()} {listing.uid} | {listing.price_eur or '?'} € | "
                            f"{listing.sqm or '?'} m² | {listing.location[:30]} | {listing.title[:50]}"
                        )
            except Exception as e:
                print(f"[run/{name}] error: {e}")
                traceback.print_exc()
        total_seen += scraper_seen
        if scraper_seen == 0:
            # An enabled scraper yielding nothing usually means the site
            # changed and the parser broke — indistinguishable from "no
            # inventory" unless we shout about it.
            send_alert(
                f"⚠️ immo-hunter: scraper '{name}' returned 0 listings — possibly broken",
                config,
            )
    return total_seen, total_new


def _parse_models(value) -> list[str]:
    """Accept a YAML list or comma-separated string; order = fallback order."""
    if isinstance(value, list):
        return [str(m).strip() for m in value if str(m).strip()]
    return [m.strip() for m in str(value).split(",") if m.strip()]


def llm_settings(config: dict) -> tuple[str, list[str], str]:
    """(backend, models, base_url) — env vars override config so the tracked
    config.yaml can stay host-neutral (Mac uses cli, Docker sets LLM_BACKEND).
    `models` is a fallback chain: first entry is primary (e.g. a free model),
    later entries are tried when it fails."""
    backend = os.environ.get("LLM_BACKEND") or config.get("llm_backend", "cli")
    models = _parse_models(
        os.environ.get("LLM_MODEL") or config.get("llm_model", "claude-sonnet-4-6")
    )
    base_url = os.environ.get("LLM_BASE_URL") or config.get("llm_base_url", "")
    return backend, models, base_url


def run_llm(config: dict, storage: Storage) -> int:
    rows = storage.unevaluated(limit=config.get("llm_max_per_run", 40))
    if not rows:
        print("[llm] nothing to evaluate")
        return 0
    print(f"\n[llm] evaluating {len(rows)} listings")
    backend, models, base_url = llm_settings(config)
    chain = ModelChain(models)
    evaluated = 0
    for row in rows:
        row = dict(row)
        # The IS24 list API carries no description; pull the expose detail
        # text once so the LLM can judge Lage/Ausstattung, not just the title.
        if row["source"] == "immoscout24" and not row["description"]:
            try:
                desc = fetch_expose_description(row["source_id"])
                if desc:
                    storage.update_description(row["uid"], desc)
                    row["description"] = desc
            except Exception as e:
                print(f"  ! {row['uid']} expose fetch failed: {e}")
        try:
            model, result = chain.call(
                lambda m: evaluate_listing(row, model=m, backend=backend, base_url=base_url)
            )
            storage.save_evaluation(
                row["uid"],
                result["score"],
                result["reasoning"],
                result["red_flags"],
                result["in_corridor"],
            )
            evaluated += 1
            print(
                f"  · {row['uid']:<45} score={result['score']:>2} [{model}] "
                f"{result['reasoning'][:70]}"
            )
        except Exception as e:
            print(f"  ! {row['uid']} llm error: {e}")
            if not chain.active():
                print("[llm] all models exhausted, stopping this run")
                break
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


def open_storage(config: dict) -> Storage:
    db_path = config.get("db_path", "../data/listings.db")
    if not Path(db_path).is_absolute():
        db_path = str(Path(__file__).parent / db_path)
    return Storage(db_path)


def run_once(config: dict, storage: Storage, args):
    if not args.skip_scrape:
        seen, new = run_scraping(config, storage)
        print(f"\n[summary/scrape] seen={seen} new={new}")
    if not args.skip_llm:
        ev = run_llm(config, storage)
        print(f"[summary/llm] evaluated={ev}")
    if not args.skip_notify:
        sent = run_notify(config, storage)
        print(f"[summary/notify] sent={sent}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--skip-notify", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument(
        "--loop",
        action="store_true",
        help="run forever, sleeping RUN_INTERVAL_MINUTES between runs (Docker mode)",
    )
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).parent / cfg_path

    if args.stats:
        import json as _json
        storage = open_storage(load_config(str(cfg_path)))
        print(_json.dumps(storage.stats(), indent=2))
        storage.close()
        return

    if not args.loop:
        config = load_config(str(cfg_path))
        storage = open_storage(config)
        run_once(config, storage, args)
        storage.close()
        return

    while True:
        # Reload config each iteration so edits to the bind-mounted file
        # take effect without a container restart.
        config = load_config(str(cfg_path))
        interval = int(
            os.environ.get("RUN_INTERVAL_MINUTES")
            or config.get("run_interval_minutes", 30)
        )
        storage = open_storage(config)
        try:
            run_once(config, storage, args)
        except Exception:
            traceback.print_exc()
        finally:
            storage.close()
        print(f"\n[loop] sleeping {interval} min")
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
