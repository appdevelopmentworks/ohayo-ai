"""Hugging Face JSON APIs: Daily Papers and trending models."""

import json
from datetime import datetime

from ai_news.models import Item
from ai_news.text import shorten


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def parse_papers(content: bytes, source_id: str) -> list[Item]:
    items = []
    for entry in json.loads(content):
        paper = entry.get("paper", {})
        paper_id = paper.get("id")
        stamp = paper.get("submittedOnDailyAt") or entry.get("publishedAt")
        title = " ".join((paper.get("title") or entry.get("title") or "").split())
        if not (paper_id and stamp and title):
            continue
        items.append(
            Item(
                source=source_id,
                title=title,
                url=f"https://arxiv.org/abs/{paper_id}",
                published=_time(stamp),
                summary=shorten(paper.get("summary") or entry.get("summary") or ""),
                points=paper.get("upvotes", 0),
                discussion_url=f"https://huggingface.co/papers/{paper_id}",
            )
        )
    return items


def parse_models(content: bytes, source_id: str) -> list[Item]:
    items = []
    for model in json.loads(content):
        model_id = model.get("id")
        created = model.get("createdAt")
        if not (model_id and created):
            continue
        facts = [f"Task: {model['pipeline_tag']}" if model.get("pipeline_tag") else ""]
        facts.append(f"Likes: {model.get('likes', 0)}")
        facts.append(f"Downloads: {model.get('downloads', 0)}")
        items.append(
            Item(
                source=source_id,
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                published=_time(created),
                summary="Trending model on Hugging Face. " + ". ".join(f for f in facts if f) + ".",
                points=model.get("trendingScore", 0),
            )
        )
    return items
