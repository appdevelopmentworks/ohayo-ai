"""Anthropic News: no RSS, so parse the listing page.

Class names on the page are build hashes, so rely on structure instead:
every article card is a link that contains a <time> element.
"""

from datetime import UTC, datetime, time
from urllib.parse import urljoin, urlsplit

import lxml.html

from ai_news.models import Item
from ai_news.text import shorten

PAGE_URL = "https://www.anthropic.com/news"
DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y")


def parse_date(text: str) -> datetime | None:
    text = " ".join(text.split())
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            day = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        # The page shows dates only (US time); end of day keeps yesterday's posts in the 36h window.
        return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)
    return None


def _text(element) -> str:
    return " ".join(element.text_content().split())


def _title(link) -> str:
    for xpath in (".//h1|.//h2|.//h3|.//h4|.//h5|.//h6", ".//*[contains(@class, 'title')]"):
        found = link.xpath(xpath)
        if found and _text(found[0]):
            return _text(found[0])
    return ""


def parse(content: bytes, source_id: str) -> list[Item]:
    doc = lxml.html.fromstring(content)
    items: list[Item] = []
    urls: set[str] = set()
    for link in doc.xpath("//a[@href][.//time]"):
        url = urljoin(PAGE_URL, link.get("href"))
        if urlsplit(url).hostname not in ("www.anthropic.com", "anthropic.com") or url in urls:
            continue
        stamp = link.xpath(".//time")[0]
        published = parse_date(stamp.get("datetime") or _text(stamp))
        title = _title(link)
        if not (published and title):
            continue
        paragraphs = link.xpath(".//p")
        urls.add(url)
        items.append(
            Item(
                source=source_id,
                title=title,
                url=url,
                published=published,
                summary=shorten(_text(paragraphs[0])) if paragraphs else "",
            )
        )
    return items
