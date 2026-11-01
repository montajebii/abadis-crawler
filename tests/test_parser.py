"""Tests for crawler.parser."""
from pathlib import Path

from crawler.parser import WordParser, normalize_canonical

FIXTURE = Path(__file__).parent / "fixtures" / "sample_word.html"
MAPPING = Path(__file__).parent.parent / "config" / "source_mapping.json"


def test_normalize_canonical_whitespace():
    assert normalize_canonical("  سلام  ") == "سلام"
    assert normalize_canonical("سلام   دنیا") == "سلام دنیا"


def test_normalize_canonical_arabic_to_persian():
    assert normalize_canonical("علي") == "علی"
    assert normalize_canonical("كتاب") == "کتاب"


def test_normalize_canonical_preserves_zwnj():
    assert "\u200c" in normalize_canonical("می\u200cرود")


def test_parse_word_page():
    html = FIXTURE.read_text(encoding="utf-8")
    parser = WordParser(MAPPING)
    result = parser.parse(html)

    assert result is not None
    assert result.display_form == "رابعا"
    assert result.canonical == "رابعا"
    assert result.pronunciation == "rAbe~an"
    assert result.english_mean == "fourthly"

    keys = {s.source_key for s in result.sections}
    assert "dehkhoda" in keys
    assert "moeen" in keys
    assert "amid" in keys
    assert "parsi" in keys

    for s in result.sections:
        assert s.source_title != "پیشنهاد کاربران"

    by_key = {s.source_key: s for s in result.sections}
    assert "چهارم" in by_key["amid"].content_text
    assert "مرتبه چهارم" in by_key["dehkhoda"].content_text


def test_parse_returns_none_for_non_word_page():
    parser = WordParser(MAPPING)
    html = "<html><body><p>not a word page</p></body></html>"
    assert parser.parse(html) is None
