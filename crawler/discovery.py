"""Parse abadis list pages and footerlinks into structured data."""
from __future__ import annotations

from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup


def extract_word_slug(href: str) -> Optional[str]:
    """Extract the Persian word slug from a URL.

    Examples:
        /fatofa/سلام/                 -> سلام
        /fatofa/%D8%B3%D9%84%D8%A7%D9%85/ -> سلام
        https://abadis.ir/amid/کتاب/   -> کتاب
    """
    if not href:
        return None
    parsed = urlparse(href)
    path = parsed.path or href
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return unquote(parts[-1])


def parse_word_list_page(html: str) -> tuple[list[str], int]:
    """Return (word_hrefs, max_page_number)."""
    soup = BeautifulSoup(html, "lxml")
    word_hrefs: list[str] = []
    for a in soup.select("div.boxLi a"):
        href = a.get("href", "")
        if href:
            word_hrefs.append(href)

    max_page = 1
    for a in soup.select("div.paging a"):
        txt = a.get_text(strip=True)
        if txt.isdigit():
            max_page = max(max_page, int(txt))
    return word_hrefs, max_page


def parse_letters(html: str) -> list[str]:
    """Extract the letter list from a dictionary base page."""
    soup = BeautifulSoup(html, "lxml")
    letters: list[str] = []
    for a in soup.select("div.boxLiCh a"):
        txt = a.get_text(strip=True)
        if txt and len(txt) <= 3:
            letters.append(txt)
    return letters


def parse_footerlinks(html: str) -> list[dict]:
    """Extract dictionary links from the footerlinks page."""
    soup = BeautifulSoup(html, "lxml")
    result: list[dict] = []
    skip_slugs = {"page", "user", "dic", "wordmaker", "footerlinks", ""}
    for a in soup.select("#ftLinks a"):
        href = a.get("href", "")
        if not href.startswith("/"):
            continue
        slug = href.strip("/").split("/")[0]
        if slug in skip_slugs:
            continue
        result.append({
            "slug": slug,
            "url": f"https://abadis.ir{href}",
            "display_name": a.get_text(strip=True),
        })
    return result
