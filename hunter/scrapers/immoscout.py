import re
import json
from typing import Iterable
from ..models import Listing
from .base import Scraper
from ._playwright_util import browser_page


class ImmoscoutScraper(Scraper):
    name = "immoscout24"

    def fetch(self, search: dict) -> Iterable[Listing]:
        region_slug = search.get("is24_region_slug")
        if not region_slug:
            print(
                "[immoscout24] missing 'is24_region_slug' (e.g. 'baden-wuerttemberg/heidelberg-kreisfreie-stadt'); skip"
            )
            return

        max_price = search.get("max_price", 1_000_000)
        min_sqm = search.get("min_sqm", 80)
        max_pages = search.get("max_pages", 2)

        base = (
            f"https://www.immobilienscout24.de/Suche/de/{region_slug}/haus-kaufen"
            f"?price=-{max_price}&livingspace={min_sqm}-"
            f"&sorting=2"  # newest first
        )

        with browser_page() as page:
            for pn in range(1, max_pages + 1):
                url = base + (f"&pagenumber={pn}" if pn > 1 else "")
                try:
                    page.goto(url, timeout=40000, wait_until="domcontentloaded")
                    # accept cookie banner if present
                    try:
                        page.click(
                            "button:has-text('Alle akzeptieren'), button:has-text('Akzeptieren')",
                            timeout=2500,
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)
                    html = page.content()
                except Exception as e:
                    print(f"[immoscout24] error {url}: {e}")
                    break

                items = self._extract(html)
                if not items:
                    break
                for l in items:
                    yield l

    def _extract(self, html: str) -> list[Listing]:
        listings: list[Listing] = []
        # Immoscout embeds JSON in IS24.resultList or window.IS24
        m = re.search(r'resultListModel"\s*:\s*({.+?})\s*,\s*"breadcrumb"', html, re.DOTALL)
        json_blob = None
        if m:
            try:
                json_blob = json.loads(m.group(1))
            except Exception:
                json_blob = None
        if json_blob:
            entries = (
                json_blob.get("searchResponseModel", {})
                .get("resultlist.resultlist", {})
                .get("resultlistEntries", [])
            )
            for entry_group in entries:
                for r in entry_group.get("resultlistEntry", []):
                    real = r.get("resultlist.realEstate") or {}
                    eid = real.get("@id") or r.get("@id")
                    if not eid:
                        continue
                    price = (real.get("price") or {}).get("value")
                    addr = real.get("address") or {}
                    listings.append(
                        Listing(
                            source=self.name,
                            source_id=str(eid),
                            url=f"https://www.immobilienscout24.de/expose/{eid}",
                            title=real.get("title", "") or "",
                            price_eur=int(price) if price else None,
                            sqm=float(real.get("livingSpace") or 0) or None,
                            rooms=float(real.get("numberOfRooms") or 0) or None,
                            location=" ".join(
                                str(addr.get(k, ""))
                                for k in ("postcode", "city", "quarter")
                                if addr.get(k)
                            ).strip(),
                            plz=addr.get("postcode"),
                            raw=real,
                        )
                    )
            return listings

        # Fallback: parse cards via HTML
        for m in re.finditer(r'data-obid="(\d+)"([\s\S]{0,3000})', html):
            eid, body = m.groups()
            title_m = re.search(r'class="result-list-entry__brand-title"[^>]*>([^<]+)', body)
            price_m = re.search(r"€\s*([\d.]+)", body)
            sqm_m = re.search(r"([\d,]+)\s*m²", body)
            listings.append(
                Listing(
                    source=self.name,
                    source_id=eid,
                    url=f"https://www.immobilienscout24.de/expose/{eid}",
                    title=title_m.group(1).strip() if title_m else f"IS24 {eid}",
                    price_eur=int(price_m.group(1).replace(".", "")) if price_m else None,
                    sqm=float(sqm_m.group(1).replace(",", ".")) if sqm_m else None,
                )
            )
        return listings
