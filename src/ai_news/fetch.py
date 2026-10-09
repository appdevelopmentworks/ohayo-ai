"""Live HTTP fetching with one retry."""

import logging
import time

import httpx

from ai_news.sources import Source

log = logging.getLogger(__name__)

USER_AGENT = "ohayo-ai/0.1 (+https://github.com/appdevelopmentworks/ohayo-ai)"
TIMEOUT = 20.0
RETRY_DELAY = 3.0


def http_fetch(source: Source, url: str) -> bytes:
    for attempt in (1, 2):
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise
            log.info("%s: retrying after %s", source.id, exc)
            time.sleep(RETRY_DELAY)
    raise AssertionError("unreachable")
