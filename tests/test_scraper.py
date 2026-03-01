from unittest.mock import AsyncMock, patch

import pytest

from pravni_kvalifikator.mcp.scraper import LawScraper


@pytest.fixture
def scraper():
    return LawScraper(delay=0.0)  # No delay in tests


class TestLawScraper:
    @pytest.mark.asyncio
    async def test_build_url(self, scraper):
        url = scraper.build_url("40/2009")
        assert url == "https://www.zakonyprolidi.cz/cs/2009-40"

    @pytest.mark.asyncio
    async def test_build_url_format(self, scraper):
        """URL format: /cs/{rok}-{cislo}."""
        url = scraper.build_url("251/2016")
        assert url == "https://www.zakonyprolidi.cz/cs/2016-251"

    @pytest.mark.asyncio
    async def test_fetch_returns_html(self, scraper):
        """fetch() returns HTML string (mocked)."""
        mock_html = "<html><body>test</body></html>"
        with patch.object(scraper, "_get", new_callable=AsyncMock, return_value=mock_html):
            html = await scraper.fetch("40/2009")
            assert "test" in html

    @pytest.mark.asyncio
    async def test_fetch_raises_on_404(self, scraper):
        """fetch() raises on HTTP error."""
        with patch.object(
            scraper, "_get", new_callable=AsyncMock, side_effect=Exception("HTTP 404")
        ):
            with pytest.raises(Exception, match="404"):
                await scraper.fetch("99/9999")
