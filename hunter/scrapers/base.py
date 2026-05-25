from abc import ABC, abstractmethod
from typing import Iterable
from ..models import Listing


class Scraper(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, search: dict) -> Iterable[Listing]:
        """Yield Listings for one configured search."""
        ...
