"""HTML parser for zakonyprolidi.cz law pages.

The HTML structure uses a flat sequence of sibling elements inside <div class="Frags">.
Structural markers are identified by CSS classes on <p> elements:
- p.CAST → Part (část)
- p.HLAVA → Head (hlava)
- p.DIL → Division (díl)
- p.PARA → Paragraph (§)
- h3.NADPIS → Heading text for the preceding structural element

Paragraph numbers are extracted from <i id="p{cislo}"> inside the <p.PARA> element.
"""

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class ParsedParagraph:
    cislo: str  # "205", "205a" — always string
    nazev: str | None = None  # "Krádež"
    plne_zneni: str = ""  # full text including odstavce/písmena


@dataclass
class ParsedDil:
    cislo: str  # "1", "2"
    nazev: str = ""
    paragraphs: list[ParsedParagraph] = field(default_factory=list)


@dataclass
class ParsedHlava:
    cislo: str  # "I", "II", "III"
    nazev: str = ""
    dily: list[ParsedDil] = field(default_factory=list)
    paragraphs: list[ParsedParagraph] = field(default_factory=list)

    def all_paragraphs(self) -> list[ParsedParagraph]:
        result = list(self.paragraphs)
        for dil in self.dily:
            result.extend(dil.paragraphs)
        return result


@dataclass
class ParsedCast:
    cislo: str  # "1", "2"
    nazev: str = ""
    hlavy: list[ParsedHlava] = field(default_factory=list)


@dataclass
class ParsedLaw:
    casti: list[ParsedCast] = field(default_factory=list)

    def all_paragraphs(self) -> list[ParsedParagraph]:
        result = []
        for cast in self.casti:
            for hlava in cast.hlavy:
                result.extend(hlava.all_paragraphs())
        return result


# Regex to extract paragraph number from <i id="p205"> or <i id="p5a">
PARA_ID_RE = re.compile(r"^p(\d+[a-z]?)$")
# Regex to extract part/head/division numbers from text
CAST_NUM_RE = re.compile(r"ČÁST\s+(\S+)", re.IGNORECASE)
HLAVA_NUM_RE = re.compile(r"HLAVA\s+(\S+)", re.IGNORECASE)
DIL_NUM_RE = re.compile(r"Díl\s+(\d+)", re.IGNORECASE)

# Structural CSS classes
STRUCTURAL_CLASSES = {"CAST", "HLAVA", "DIL", "PARA"}


def _has_class(tag: Tag, cls: str) -> bool:
    """Check if tag has a specific CSS class."""
    classes = tag.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    return cls in classes


def _is_cancelled(tag: Tag) -> bool:
    """Check if a PARA element is cancelled (zrušeno)."""
    return _has_class(tag, "SIL")


def _extract_para_cislo(tag: Tag) -> str | None:
    """Extract paragraph number from <i id="p{cislo}"> inside a PARA element."""
    i_tag = tag.find("i", id=PARA_ID_RE)
    if i_tag and isinstance(i_tag.get("id"), str):
        match = PARA_ID_RE.match(i_tag["id"])
        if match:
            return match.group(1)
    # Fallback: extract from text "§ NNN"
    text = tag.get_text(strip=True)
    para_match = re.search(r"§\s*(\d+[a-z]?)", text)
    if para_match:
        return para_match.group(1)
    return None


class LawParser:
    """Parses zakonyprolidi.cz HTML into structured law data.

    Uses a state machine over the flat sibling sequence inside <div class="Frags">.
    """

    def parse(self, html: str) -> ParsedLaw:
        """Parse full law HTML page into ParsedLaw structure."""
        soup = BeautifulSoup(html, "html.parser")
        law = ParsedLaw()

        # Find the main content area
        frags = soup.select_one("div.Frags")
        if frags is None:
            logger.warning("Could not find div.Frags in HTML")
            return law

        # Parse the flat sibling sequence
        law = self._parse_siblings(frags)

        logger.info(
            "Parsed law: %d částí, %d paragrafů",
            len(law.casti),
            len(law.all_paragraphs()),
        )
        return law

    def _parse_siblings(self, frags: Tag) -> ParsedLaw:
        """Walk through direct children of div.Frags as a state machine."""
        law = ParsedLaw()
        current_cast: ParsedCast | None = None
        current_hlava: ParsedHlava | None = None
        current_dil: ParsedDil | None = None
        current_para: ParsedParagraph | None = None
        has_explicit_casti = False
        # Track the last structural element to assign NADPIS headings
        last_structural: str | None = None  # "cast", "hlava", "dil", "para"
        body_lines: list[str] = []

        def flush_paragraph():
            """Finalize current paragraph and attach to correct parent."""
            nonlocal current_para, body_lines
            if current_para is not None:
                current_para.plne_zneni = "\n".join(body_lines).strip()
                target = current_dil or current_hlava
                if target is not None:
                    if isinstance(target, ParsedDil):
                        target.paragraphs.append(current_para)
                    else:
                        target.paragraphs.append(current_para)
                current_para = None
                body_lines = []

        def ensure_hlava():
            """Ensure we have a current hlava (create implicit one if needed)."""
            nonlocal current_hlava, current_dil
            if current_hlava is None:
                current_hlava = ParsedHlava(cislo="", nazev="")
                current_dil = None

        def ensure_cast():
            """Ensure we have a current cast (create implicit one if needed)."""
            nonlocal current_cast
            if current_cast is None:
                current_cast = ParsedCast(cislo="1", nazev="")

        def flush_hlava():
            nonlocal current_hlava, current_dil
            flush_paragraph()
            if current_hlava is not None:
                ensure_cast()
                current_cast.hlavy.append(current_hlava)
                current_hlava = None
                current_dil = None

        def flush_cast():
            nonlocal current_cast
            flush_hlava()
            if current_cast is not None:
                law.casti.append(current_cast)
                current_cast = None

        for child in frags.children:
            if not isinstance(child, Tag):
                continue

            # ── CAST (Part) ──
            if child.name == "p" and _has_class(child, "CAST"):
                flush_cast()
                has_explicit_casti = True
                text = child.get_text(strip=True)
                match = CAST_NUM_RE.search(text)
                cislo = match.group(1) if match else text
                current_cast = ParsedCast(cislo=cislo, nazev="")
                last_structural = "cast"
                continue

            # ── HLAVA (Head) ──
            if child.name == "p" and _has_class(child, "HLAVA"):
                flush_hlava()
                ensure_cast()
                text = child.get_text(strip=True)
                match = HLAVA_NUM_RE.search(text)
                cislo = match.group(1) if match else text
                current_hlava = ParsedHlava(cislo=cislo, nazev="")
                current_dil = None
                last_structural = "hlava"
                continue

            # ── DIL (Division) ──
            if child.name == "p" and _has_class(child, "DIL"):
                flush_paragraph()
                ensure_hlava()
                text = child.get_text(strip=True)
                match = DIL_NUM_RE.search(text)
                cislo = match.group(1) if match else text
                current_dil = ParsedDil(cislo=cislo, nazev="")
                current_hlava.dily.append(current_dil)
                last_structural = "dil"
                continue

            # ── NADPIS (Heading text for preceding structural element) ──
            if child.name == "h3" and _has_class(child, "NADPIS"):
                heading_text = child.get_text(strip=True)
                if last_structural == "cast" and current_cast is not None:
                    current_cast.nazev = heading_text
                elif last_structural == "hlava" and current_hlava is not None:
                    current_hlava.nazev = heading_text
                elif last_structural == "dil" and current_dil is not None:
                    current_dil.nazev = heading_text
                elif last_structural == "para" and current_para is not None:
                    current_para.nazev = heading_text
                last_structural = None
                continue

            # ── PARA (Paragraph §) ──
            if child.name == "p" and _has_class(child, "PARA"):
                # Skip cancelled paragraphs
                if _is_cancelled(child):
                    flush_paragraph()
                    last_structural = None
                    continue

                flush_paragraph()
                ensure_hlava()

                cislo = _extract_para_cislo(child)
                if cislo is None:
                    continue

                current_para = ParsedParagraph(cislo=cislo)
                body_lines = []
                last_structural = "para"
                continue

            # ── Body text (odstavce, písmena) ──
            if child.name == "p" and current_para is not None:
                # This is a body line of the current paragraph
                classes = child.get("class", [])
                if isinstance(classes, str):
                    classes = classes.split()
                # Skip if it has a structural class (shouldn't happen, but be safe)
                if STRUCTURAL_CLASSES.intersection(classes):
                    continue
                text = child.get_text(separator=" ", strip=True)
                if text:
                    body_lines.append(text)
                continue

        # Flush remaining state
        flush_cast()

        # If no explicit parts were found, ensure we have at least one
        if not has_explicit_casti and not law.casti:
            # Edge case: law with no structure at all
            pass

        return law
