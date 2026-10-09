import pytest

from ai_news import article, fixtures, llm, pipeline


@pytest.fixture(scope="session")
def edition():
    """The edition --dry-run builds from the recorded sources and LLM answers."""
    result = pipeline.run(
        fixtures.recorded_at(),
        fixtures.fixture_fetch,
        seen={},
        health={},
        llm=llm.LLM([llm.ReplayClient()]),
        body_fetch=article.feed_text_body,
    )
    return result.edition
