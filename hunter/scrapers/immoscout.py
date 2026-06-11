"""Immoscout24 scraper via the mobile-app API (api.mobile.immobilienscout24.de).

The website is protected by DataDome captcha and is not reliably scrapable.
The mobile API used by the IS24 phone app has no such gate. Approach borrowed
from flathunter's immobilienscout crawler.
"""
import re
import time
import urllib.request
import urllib.parse
import json
from typing import Iterable, Optional
from ..models import Listing
from .base import Scraper


API_URL = "https://api.mobile.immobilienscout24.de/search/list"
EXPOSE_URL = "https://api.mobile.immobilienscout24.de/expose/{id}"
HEADERS = {
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "ImmoScout_27.3_26.0_._",
}


def fetch_expose_description(expose_id: str) -> str:
    """Fetch detail text for one expose from the mobile API.

    The list endpoint returns no description, so the LLM would otherwise
    score IS24 listings on title/price/location alone. The expose endpoint
    carries TEXT_AREA sections (Objektbeschreibung, Ausstattung, Lage, ...).
    """
    url = EXPOSE_URL.format(id=urllib.parse.quote(str(expose_id)))
    req = urllib.request.Request(
        url, headers={k: v for k, v in HEADERS.items() if k != "Content-Type"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return extract_expose_text(data)


def extract_expose_text(data: dict) -> str:
    parts = []
    for section in data.get("sections") or []:
        if section.get("type") == "TEXT_AREA" and section.get("text"):
            title = section.get("title") or ""
            parts.append(f"{title}:\n{section['text']}" if title else section["text"])
    return "\n\n".join(parts)[:4000]


class ImmoscoutScraper(Scraper):
    name = "immoscout24"

    def fetch(self, search: dict) -> Iterable[Listing]:
        # radius search around a coordinate (default: Heidelberg Bismarckplatz)
        lat = search.get("lat", 49.3988)
        lon = search.get("lon", 8.6724)
        radius = search.get("radius_km", 20)
        max_price = search.get("max_price", 1_000_000)
        min_sqm = search.get("min_sqm", 80)
        max_pages = search.get("max_pages", 2)
        real_estate_type = search.get("realestatetype", "housebuy")

        params = {
            "searchType": "radius",
            "realEstateType": real_estate_type,
            "geocoordinates": f"{lat};{lon};{float(radius)}",
            "price": f"-{max_price}",
            "livingspace": f"{float(min_sqm)}-",
            "pagesize": 50,
            "sorting": "-firstactivation",  # newest first
        }

        for page in range(1, max_pages + 1):
            params["pagenumber"] = page
            url = API_URL + "?" + urllib.parse.urlencode(params)
            try:
                data = self._post(url)
            except Exception as e:
                print(f"[immoscout24] api error page {page}: {e}")
                break

            items = [
                i for i in (data.get("resultListItems") or [])
                if i.get("type") == "EXPOSE_RESULT"
            ]
            if not items:
                break
            for it in items:
                yield self._to_listing(it["item"])

            paging = data.get("paging") or {}
            if page >= (paging.get("numberOfPages") or max_pages):
                break
            time.sleep(1.0)

    def _post(self, url: str) -> dict:
        body = json.dumps({"supportedResultListType": [], "userData": {}}).encode()
        req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _to_listing(self, x: dict) -> Listing:
        eid = str(x.get("id"))
        attrs = [a.get("value", "") for a in x.get("attributes", [])]
        price = sqm = rooms = None
        for a in attrs:
            if "€" in a:
                price = self._num(a)
            elif "m²" in a:
                sqm = self._fnum(a)
            elif "Zi" in a:
                rooms = self._fnum(a)
        addr = x.get("address", {}).get("line", "")
        m = re.search(r"\b(\d{5})\b", addr)
        plz = m.group(1) if m else None
        pic = x.get("titlePicture", {}).get("preview")
        return Listing(
            source=self.name,
            source_id=eid,
            url=f"https://www.immobilienscout24.de/expose/{eid}",
            title=x.get("title", "") or "",
            price_eur=price,
            sqm=sqm,
            rooms=rooms,
            location=addr,
            plz=plz,
            image_url=pic,
            raw={"attributes": attrs},
        )

    @staticmethod
    def _num(s: str) -> Optional[int]:
        d = re.sub(r"[^\d]", "", s.split(",")[0])
        return int(d) if d else None

    @staticmethod
    def _fnum(s: str) -> Optional[float]:
        m = re.search(r"([\d.,]+)", s)
        if not m:
            return None
        return float(m.group(1).replace(".", "").replace(",", "."))
