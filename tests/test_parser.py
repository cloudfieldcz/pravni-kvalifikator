from pathlib import Path

import pytest

from pravni_kvalifikator.mcp.parser import LawParser, ParsedLaw

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser():
    return LawParser()


@pytest.fixture
def tz_html():
    """Trestní zákoník HTML fixture."""
    path = FIXTURES / "zakon_40_2009_sample.html"
    if not path.exists():
        pytest.skip("Fixture zakon_40_2009_sample.html not found")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def pz_html():
    """Přestupkový zákon HTML fixture."""
    path = FIXTURES / "zakon_251_2016_sample.html"
    if not path.exists():
        pytest.skip("Fixture zakon_251_2016_sample.html not found")
    return path.read_text(encoding="utf-8")


class TestLawParser:
    def test_parse_returns_parsed_law(self, parser, tz_html):
        result = parser.parse(tz_html)
        assert isinstance(result, ParsedLaw)

    def test_parsed_law_has_parts(self, parser, tz_html):
        """TZ has parts (OBECNÁ ČÁST, ZVLÁŠTNÍ ČÁST)."""
        result = parser.parse(tz_html)
        assert len(result.casti) >= 2

    def test_parsed_law_has_hlavy(self, parser, tz_html):
        """TZ has multiple hlavy."""
        result = parser.parse(tz_html)
        all_hlavy = []
        for cast in result.casti:
            all_hlavy.extend(cast.hlavy)
        assert len(all_hlavy) >= 10  # TZ has many hlavy

    def test_parsed_law_has_paragraphs(self, parser, tz_html):
        """TZ has hundreds of paragraphs."""
        result = parser.parse(tz_html)
        all_paragraphs = result.all_paragraphs()
        assert len(all_paragraphs) >= 100  # TZ has ~420 paragraphs

    def test_paragraph_has_cislo(self, parser, tz_html):
        result = parser.parse(tz_html)
        paragraphs = result.all_paragraphs()
        for p in paragraphs[:10]:
            assert p.cislo, f"Paragraph missing cislo: {p}"

    def test_paragraph_has_text(self, parser, tz_html):
        result = parser.parse(tz_html)
        paragraphs = result.all_paragraphs()
        for p in paragraphs[:10]:
            assert p.plne_zneni.strip(), f"Paragraph {p.cislo} has empty text"

    def test_paragraph_205_is_kradez(self, parser, tz_html):
        """§ 205 TZ should be Krádež."""
        result = parser.parse(tz_html)
        p205 = next((p for p in result.all_paragraphs() if p.cislo == "205"), None)
        assert p205 is not None, "§ 205 not found"
        # Check name or content matches Krádež
        assert "krádež" in (p205.nazev or "").lower() or "přisvojí" in p205.plne_zneni.lower()

    def test_paragraph_cislo_as_string(self, parser, tz_html):
        """Paragraphs like § 205a must preserve the 'a' suffix."""
        result = parser.parse(tz_html)
        all_cisla = [p.cislo for p in result.all_paragraphs()]
        # TZ contains §§ with letter suffixes
        assert any(c[-1].isalpha() for c in all_cisla if c), "TZ should have § with letter suffix"
        # All cislo values must be strings
        for c in all_cisla:
            assert isinstance(c, str)

    def test_simpler_law_parses(self, parser, pz_html):
        """Přestupkový zákon (different structure) also parses."""
        result = parser.parse(pz_html)
        assert isinstance(result, ParsedLaw)
        assert len(result.all_paragraphs()) > 0
