"""Tests for crawler.discovery."""
from crawler.discovery import (
    extract_word_slug,
    parse_footerlinks,
    parse_letters,
    parse_word_list_page,
)


def test_extract_word_slug_simple():
    assert extract_word_slug("/fatofa/سلام/") == "سلام"


def test_extract_word_slug_url_encoded():
    assert extract_word_slug("/fatofa/%D8%B3%D9%84%D8%A7%D9%85/") == "سلام"


def test_extract_word_slug_with_dash():
    assert extract_word_slug("/amid/رئیس-الوزرا/") == "رئیس-الوزرا"


def test_extract_word_slug_absolute_url():
    assert extract_word_slug("https://abadis.ir/fatofa/کتاب/") == "کتاب"


def test_extract_word_slug_invalid():
    assert extract_word_slug("") is None
    assert extract_word_slug("/single/") is None


def test_parse_word_list_page():
    html = """
    <div class='boxLi'>
      <a href="/fatofa/ر/">ر</a>
      <a href="/fatofa/رئال/">رئال</a>
      <a href="/fatofa/رئالیست/">رئالیست</a>
    </div>
    <div class='paging'>
      <a class='pagingAc'>1</a>
      <a href='?ch=ر&pn=2'>2</a>
      <a href='?ch=ر&pn=10'>10</a>
    </div>
    """
    hrefs, max_pages = parse_word_list_page(html)
    assert hrefs == ["/fatofa/ر/", "/fatofa/رئال/", "/fatofa/رئالیست/"]
    assert max_pages == 10


def test_parse_word_list_page_no_pagination():
    html = '<div class="boxLi"><a href="/fatofa/سلام/">سلام</a></div>'
    hrefs, max_pages = parse_word_list_page(html)
    assert hrefs == ["/fatofa/سلام/"]
    assert max_pages == 1


def test_parse_letters():
    html = """
    <div class='boxLiCh'>
      <a href="/amid/?ch=ا">ا</a>
      <a href="/amid/?ch=ب">ب</a>
      <a href="/amid/?ch=پ">پ</a>
    </div>
    """
    assert parse_letters(html) == ["ا", "ب", "پ"]


def test_parse_footerlinks():
    html = """
    <div id='ftLinks'>
      <a href='/dehkhoda/'>لغت نامه دهخدا</a>
      <a href='/amid/'>فرهنگ فارسی عمید</a>
      <a href='/page/about/'>معرفی</a>
    </div>
    """
    links = parse_footerlinks(html)
    slugs = [l["slug"] for l in links]
    assert "dehkhoda" in slugs
    assert "amid" in slugs
    assert "page" not in slugs
