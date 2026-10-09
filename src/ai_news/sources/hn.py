"""Hacker News via the Algolia API, keeping only AI-related stories."""

import json
import re
from datetime import UTC, datetime

from ai_news.models import Item

AI_PATTERN = re.compile(
    r"\b("
    r"ai|agi|llms?|large language models?|language models?|gpt[\w.\-]*|chatgpt|openai|anthropic"
    r"|claude|gemini|gemma|deepmind|mistral|llama|qwen|deepseek|grok|xai|copilot|codex"
    r"|hugging ?face|transformers?|diffusion|neural|machine learning|deep learning"
    r"|agents?|agentic|chatbots?|embeddings?|fine-?tun\w*|rag|prompts?|prompting"
    r"|(?:opus|sonnet|haiku) \d[\d.]*|speech[- ]to[- ]text|text[- ]to[- ](?:speech|image|video)"
    r")\b",
    re.IGNORECASE,
)


def is_ai_related(title: str) -> bool:
    return bool(AI_PATTERN.search(title))


def parse(content: bytes, source_id: str) -> list[Item]:
    items = []
    for hit in json.loads(content).get("hits", []):
        title = " ".join((hit.get("title") or "").split())
        if not title or not is_ai_related(title):
            continue
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        items.append(
            Item(
                source=source_id,
                title=title,
                url=hit.get("url") or discussion,
                published=datetime.fromtimestamp(hit["created_at_i"], UTC),
                points=hit.get("points") or 0,
                discussion_url=discussion,
            )
        )
    return items
