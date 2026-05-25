import re
import json
from typing import Iterable
from ..models import Listing
from .base import Scraper
from ._playwright_util import browser_page


class ImmoweltScraper(Scraper):
    name = "immowelt"

    def fetch(self, search: dict) -> Iterable[Listing]:
        location_code = search.get("immowelt_location_code")
        if not location_code:
            print("[immowelt] missing 'immowelt_location_code' in config (e.g. AD08DE...); skip")
            return

        max_price = search.get("max_price", 1_000_000)
        min_sqm = search.get("min_sqm", 80)
        max_pages = search.get("max_pages", 2)

        base = (
            f"https://www.immowelt.de/classified-search?"
            f"distributionTypes=Buy&estateTypes=House"
            f"&locations={location_code}"
            f"&priceMax={max_price}&livingSpaceMin={min_sqm}"
            f"&order=DateDesc"
        )

        with browser_page() as page:
            for pn in range(1, max_pages + 1):
                url = base + (f"&page={pn}" if pn > 1 else "")
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)
                    html = page.content()
                except Exception as e:
                    print(f"[immowelt] error {url}: {e}")
                    break

                listings = self._extract(html)
                if not listings:
                    break
                for l in listings:
                    yield l

    def _extract(self, html: str) -> list[Listing]:
        # Modern Immowelt embeds listing data in a script tag with state.
        listings: list[Listing] = []
        # Try Next-style JSON blob first
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                items = self._walk_for_items(data)
                for it in items:
                    l = self._item_to_listing(it)
                    if l:
                        listings.append(l)
                if listings:
                    return listings
            except Exception:
                pass
        # Fallback: extract expose IDs + scrape minimal info from HTML around them
        for m in re.finditer(
            r'href="(/expose/([a-z0-9-]+))"[^>]*>([\s\S]{0,2000})', html
        ):
            href, eid, ctx = m.groups()
            title_m = re.search(r"<h2[^>]*>([^<]+)</h2>", ctx)
            price_m = re.search(r"(\d[\d.\s]{2,})\s*€", ctx)
            sqm_m = re.search(r"(\d{2,4})\s*m²", ctx)
            listings.append(
                Listing(
                    source=self.name,
                    source_id=eid,
                    url=f"https://www.immowelt.de/expose/{eid}",
                    title=title_m.group(1).strip() if title_m else f"Immowelt {eid}",
                    price_eur=int(re.sub(r"\D", "", price_m.group(1))) if price_m else None,
                    sqm=float(sqm_m.group(1)) if sqm_m else None,
                    location="",
                )
            )
        # Dedupe
        seen = set()
        out = []
        for l in listings:
            if l.source_id in seen:
                continue
            seen.add(l.source_id)
            out.append(l)
        return out

    def _walk_for_items(self, node, path="") -> list[dict]:
        results = []
        if isinstance(node, dict):
            if "estateId" in node or ("id" in node and "price" in node and "title" in node):
                results.append(node)
            for k, v in node.items():
                results.extend(self._walk_for_items(v, path + "." + k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                results.extend(self._walk_for_items(v, path + f"[{i}]"))
        return results

    def _item_to_listing(self, it: dict):
        eid = it.get("estateId") or it.get("id")
        if not eid:
            return None
        price = it.get("price") or {}
        if isinstance(price, dict):
            price_val = price.get("amount") or price.get("value")
        else:
            price_val = price
        area = it.get("livingSpace") or it.get("area")
        if isinstance(area, dict):
            area_val = area.get("amount") or area.get("value")
        else:
            area_val = area
        loc = it.get("place") or it.get("location") or {}
        loc_str = ""
        if isinstance(loc, dict):
            loc_str = " ".join(
                str(loc.get(k, "")) for k in ("postcode", "city", "district") if loc.get(k)
            )
        return Listing(
            source=self.name,
            source_id=str(eid),
            url=f"https://www.immowelt.de/expose/{eid}",
            title=it.get("title", "") or "",
            price_eur=int(price_val) if price_val else None,
            sqm=float(area_val) if area_val else None,
            rooms=float(it.get("roomsCount") or it.get("rooms") or 0) or None,
            location=loc_str.strip(),
            description=(it.get("description") or "")[:2000],
            image_url=(it.get("pictures") or [{}])[0].get("url") if it.get("pictures") else None,
            raw=it,
        )
