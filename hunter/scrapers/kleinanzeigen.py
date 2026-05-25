import re
import gzip
import json
import urllib.request
import urllib.parse
import time
from typing import Iterable, Optional
from ..models import Listing
from .base import Scraper


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

PRICE_RE = re.compile(r"aditem-main--middle--price-shipping--price[^>]*>\s*([^<]+)")
LOC_RE = re.compile(r"icon-pin-gray[^>]*></i>\s*([^<\n]+)")
TITLE_RE = re.compile(r'"title":"([^"]+)"')
DESC_RE = re.compile(r'"description":"([^"]+)"')
IMG_RE = re.compile(r'"contentUrl":"([^"]+)"')
SQM_RE = re.compile(r"(\d{2,4}(?:[.,]\d+)?)\s*m²")
ROOMS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:Zi|Zimmer)")
PLZ_RE = re.compile(r"\b(\d{5})\b")
BLOCK_RE = re.compile(
    r'data-adid="(\d+)"\s+data-href="([^"]+)"([\s\S]*?)(?=data-adid=|</body>)'
)


def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")


def _parse_price(s: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def resolve_location_id(city: str) -> Optional[str]:
    """Use kleinanzeigen's autocomplete to get numeric location id."""
    url = f"https://www.kleinanzeigen.de/s-ort-empfehlungen.json?query={urllib.parse.quote(city)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        data = json.loads(raw)
    for k in data:
        if k != "_0":
            return k.lstrip("_")
    return None


class KleinanzeigenScraper(Scraper):
    name = "kleinanzeigen"

    def fetch(self, search: dict) -> Iterable[Listing]:
        city = search.get("city", "Heidelberg")
        radius = search.get("radius_km", 20)
        max_pages = search.get("max_pages", 2)
        min_price = search.get("min_price", 0)
        max_price = search.get("max_price", 10_000_000)
        category = search.get("category", "c208")  # c208 = Häuser zum Kauf

        loc_id = resolve_location_id(city)
        if not loc_id:
            return

        for page in range(1, max_pages + 1):
            page_seg = "" if page == 1 else f"seite:{page}/"
            url = (
                f"https://www.kleinanzeigen.de/s-haus-kaufen/{page_seg}"
                f"preis:{min_price}:{max_price}/{urllib.parse.quote(city.lower())}/"
                f"{category}l{loc_id}r{radius}"
            )
            try:
                html = _fetch(url)
            except Exception as e:
                print(f"[kleinanzeigen] fetch error {url}: {e}")
                break

            blocks = BLOCK_RE.findall(html)
            if not blocks:
                break

            for adid, href, body in blocks:
                yield self._parse_block(adid, href, body)

            time.sleep(1.5)

    def _parse_block(self, adid: str, href: str, body: str) -> Listing:
        t = TITLE_RE.search(body)
        d = DESC_RE.search(body)
        p = PRICE_RE.search(body)
        loc = LOC_RE.search(body)
        img = IMG_RE.search(body)

        title = t.group(1) if t else ""
        description = (d.group(1) if d else "").replace("\\n", "\n")
        price = _parse_price(p.group(1)) if p else None
        loc_text = re.sub(r"\s+", " ", loc.group(1).strip()) if loc else ""
        plz_m = PLZ_RE.search(loc_text)
        plz = plz_m.group(1) if plz_m else None

        sqm = None
        rooms = None
        for src in (title, description):
            if sqm is None:
                m = SQM_RE.search(src)
                if m:
                    sqm = float(m.group(1).replace(",", "."))
            if rooms is None:
                m = ROOMS_RE.search(src)
                if m:
                    rooms = float(m.group(1).replace(",", "."))

        return Listing(
            source=self.name,
            source_id=adid,
            url=f"https://www.kleinanzeigen.de{href}",
            title=title,
            price_eur=price,
            sqm=sqm,
            rooms=rooms,
            location=loc_text,
            plz=plz,
            description=description[:2000],
            image_url=img.group(1) if img else None,
            raw={"href": href},
        )
