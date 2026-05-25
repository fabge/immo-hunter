"""Generic RSS reader for Immoscout24 Sparalarm and similar feeds."""
import re
from typing import Iterable
from ..models import Listing
from .base import Scraper


class RssScraper(Scraper):
    name = "rss"

    def fetch(self, search: dict) -> Iterable[Listing]:
        try:
            import feedparser
        except ImportError:
            raise RuntimeError("feedparser not installed. pip install feedparser")

        feeds = search.get("feeds", [])
        for feed_cfg in feeds:
            url = feed_cfg["url"]
            label = feed_cfg.get("label", "rss")
            d = feedparser.parse(url)
            if d.bozo:
                print(f"[rss/{label}] feed parse warning: {d.bozo_exception}")
            for entry in d.entries:
                yield self._entry_to_listing(entry, label)

    def _entry_to_listing(self, entry, label: str) -> Listing:
        link = entry.get("link", "")
        eid = self._extract_id(link)
        title = entry.get("title", "")
        desc = entry.get("summary", "") or entry.get("description", "")
        plain_desc = re.sub(r"<[^>]+>", " ", desc)
        price_m = re.search(r"([\d.,]+)\s*€", plain_desc)
        sqm_m = re.search(r"([\d,]+)\s*m²", plain_desc)
        rooms_m = re.search(r"([\d,]+)\s*Zimmer", plain_desc)
        return Listing(
            source=f"rss:{label}",
            source_id=eid,
            url=link,
            title=title,
            price_eur=int(re.sub(r"\D", "", price_m.group(1))) if price_m else None,
            sqm=float(sqm_m.group(1).replace(",", ".")) if sqm_m else None,
            rooms=float(rooms_m.group(1).replace(",", ".")) if rooms_m else None,
            description=plain_desc.strip()[:2000],
        )

    def _extract_id(self, url: str) -> str:
        m = re.search(r"/(\d{6,})", url)
        if m:
            return m.group(1)
        return url.rsplit("/", 1)[-1][:64] or url
