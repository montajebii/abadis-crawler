"""Parse an abadis word page into structured sections."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

# Arabic -> Persian character normalization
_NORM_MAP = str.maketrans({
    "\u064A": "\u06CC",  # ي -> ی
    "\u0643": "\u06A9",  # ك -> ک
})
_WS_RE = re.compile(r"[ \t\u00A0]+")


def normalize_canonical(s: str) -> str:
    """Normalize a word string for canonical matching."""
    if not s:
        return ""
    s = s.strip()
    s = s.translate(_NORM_MAP)
    s = _WS_RE.sub(" ", s)
    return s


@dataclass
class ParsedSection:
    source_key: str
    source_title: str
    content_text: str


@dataclass
class ParsedWord:
    display_form: str
    canonical: str
    pronunciation: Optional[str]
    english_mean: Optional[str]
    sections: list[ParsedSection] = field(default_factory=list)


class WordParser:
    def __init__(self, source_mapping_path: Path):
        with open(source_mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._mapping: dict[str, str] = data.get("mappings", {})
        self._excluded: set[str] = set(data.get("excluded_titles", []))

    def _map_source(self, title: str) -> Optional[str]:
        if title in self._excluded:
            return None
        if title in self._mapping:
            return self._mapping[title]
        # Unknown title: use a stable, derived key so we never lose data.
        # Future abadis additions will show up as custom_<title> instead
        # of being silently dropped.
        key = normalize_canonical(title).replace(" ", "_")
        return f"custom_{key}"

    def parse(
        self,
        html: str,
        skip_unknown_sources: bool = True,
    ) -> Optional[ParsedWord]:
        soup = BeautifulSoup(html, "lxml")

        box_main = soup.find("div", class_="boxMain")
        if not box_main:
            return None
        box_wrd = box_main.find("div", id="boxWrd")
        if not box_wrd:
            return None
        h1 = box_wrd.find("h1")
        if not h1:
            return None
        display_form = h1.get_text(strip=True)
        if not display_form:
            return None
        canonical = normalize_canonical(display_form)

        pronunciation: Optional[str] = None
        pron_el = box_wrd.find("div", class_="boxLtr")
        if pron_el:
            txt = pron_el.get_text(strip=True).strip("/").strip()
            if txt:
                pronunciation = txt

        english_mean: Optional[str] = None
        eng_box = box_main.find("div", class_="boxEnMean")
        if eng_box:
            l_el = eng_box.find("l")
            if l_el:
                txt = l_el.get_text(strip=True)
                if txt:
                    english_mean = txt

        sections: list[ParsedSection] = []
        for lun in soup.find_all("div", class_="lun"):
            title = lun.get("t")
            if not title:
                continue
            source_key = self._map_source(title)
            if source_key is None:
                if skip_unknown_sources:
                    continue
                source_key = "unknown_" + normalize_canonical(title)

            content_el = None
            for selector in ("article", "div.boxBd", "div.boxBdNop"):
                content_el = lun.select_one(selector)
                if content_el:
                    break
            if content_el is None:
                continue

            content_text = content_el.get_text("\n", strip=True)
            if not content_text:
                continue

            sections.append(
                ParsedSection(
                    source_key=source_key,
                    source_title=title,
                    content_text=content_text,
                )
            )

        return ParsedWord(
            display_form=display_form,
            canonical=canonical,
            pronunciation=pronunciation,
            english_mean=english_mean,
            sections=sections,
        )
