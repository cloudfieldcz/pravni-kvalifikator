"""HTTP scraper for zakonyprolidi.cz law pages."""

import asyncio
import logging

import httpx

from pravni_kvalifikator.shared.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zakonyprolidi.cz/cs"


class LawScraper:
    """Downloads law pages from zakonyprolidi.cz."""

    def __init__(self, delay: float | None = None, user_agent: str | None = None):
        settings = get_settings()
        self.delay = delay if delay is not None else settings.scraper_delay
        self.user_agent = user_agent or settings.scraper_user_agent
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return shared httpx client (reuses TCP connections)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
                timeout=30.0,
            )
        return self._client

    def build_url(self, sbirkove_cislo: str) -> str:
        """Build URL from sbírkové číslo. '40/2009' → '/cs/2009-40'."""
        cislo, rok = sbirkove_cislo.split("/")
        return f"{BASE_URL}/{rok}-{cislo}"

    async def fetch(self, sbirkove_cislo: str) -> str:
        """Fetch law page HTML. Raises on HTTP error."""
        url = self.build_url(sbirkove_cislo)
        logger.info("Fetching %s", url)
        html = await self._get(url)
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return html

    async def _get(self, url: str) -> str:
        """HTTP GET with shared client (reuses connections)."""
        client = await self._get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    async def fetch_many(self, sbirkova_cisla: list[str]) -> dict[str, str]:
        """Fetch multiple laws sequentially (polite scraping)."""
        results = {}
        for sc in sbirkova_cisla:
            try:
                results[sc] = await self.fetch(sc)
                logger.info("Fetched %s", sc)
            except Exception as e:
                logger.error("Failed to fetch %s: %s", sc, e)
        return results

    async def close(self) -> None:
        """Close the shared httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
