from dataclasses import dataclass, field, asdict
from typing import Optional
import hashlib
import json


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    price_eur: Optional[int] = None
    sqm: Optional[float] = None
    rooms: Optional[float] = None
    location: str = ""
    plz: Optional[str] = None
    description: str = ""
    image_url: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def price_per_sqm(self) -> Optional[float]:
        if self.price_eur and self.sqm and self.sqm > 0:
            return round(self.price_eur / self.sqm, 1)
        return None

    def content_hash(self) -> str:
        payload = json.dumps(
            {"t": self.title, "p": self.price_eur, "s": self.sqm, "l": self.location},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)
