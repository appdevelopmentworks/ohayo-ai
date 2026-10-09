"""Data models shared across the pipeline."""

from pydantic import AwareDatetime, BaseModel, Field


class Item(BaseModel):
    """One candidate news item collected from a source."""

    source: str
    title: str
    url: str  # primary source; what the card links to
    published: AwareDatetime
    summary: str = ""  # plain text from the feed, already shortened
    points: int | None = None  # HN points, paper upvotes, trending score
    discussion_url: str | None = None  # HN thread, HF paper page, blog post that linked it
    also_in: dict[str, int | None] = Field(default_factory=dict)  # merged duplicates: source -> points
