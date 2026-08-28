from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_visible_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


@dataclass(frozen=True, slots=True)
class SeoHtmlSignals:
    title: str | None
    description: str | None
    canonical: str | None
    robots: str | None
    h1: tuple[str, ...]
    json_ld_types: tuple[str, ...]
    internal_links: tuple[str, ...]
    visible_text: str


class _SeoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.canonical: str | None = None
        self.robots: str | None = None
        self.h1_values: list[str] = []
        self.json_ld_documents: list[Any] = []
        self.internal_links: list[str] = []
        self.visible_text_parts: list[str] = []
        self._in_body = False
        self._hidden_depth = 0
        self._title_parts: list[str] | None = None
        self._h1_parts: list[str] | None = None
        self._json_ld_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attributes = {str(key).lower(): str(value or "") for key, value in attrs}

        if normalized_tag == "body":
            self._in_body = True
        if normalized_tag in {"script", "style", "template", "noscript"}:
            self._hidden_depth += 1
        if normalized_tag == "title":
            self._title_parts = []
        elif normalized_tag == "h1":
            self._h1_parts = []
        elif normalized_tag == "meta":
            meta_name = attributes.get("name", "").strip().lower()
            content = attributes.get("content", "").strip() or None
            if meta_name == "description" and self.description is None:
                self.description = content
            elif meta_name == "robots" and self.robots is None:
                self.robots = content
        elif normalized_tag == "link":
            rel_tokens = {token.lower() for token in attributes.get("rel", "").split()}
            if "canonical" in rel_tokens and self.canonical is None:
                self.canonical = attributes.get("href", "").strip() or None
        elif normalized_tag == "a":
            href = attributes.get("href", "").strip()
            if href:
                self.internal_links.append(href)

        if normalized_tag == "script" and attributes.get("type", "").strip().lower() == "application/ld+json":
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title" and self._title_parts is not None:
            self.title = normalize_visible_text("".join(self._title_parts)) or None
            self._title_parts = None
        elif normalized_tag == "h1" and self._h1_parts is not None:
            h1_text = normalize_visible_text(" ".join(self._h1_parts))
            if h1_text:
                self.h1_values.append(h1_text)
            self._h1_parts = None
        elif normalized_tag == "script" and self._json_ld_parts is not None:
            raw_json = "".join(self._json_ld_parts).strip()
            if raw_json:
                try:
                    self.json_ld_documents.append(json.loads(raw_json))
                except json.JSONDecodeError:
                    self.json_ld_documents.append({"_invalid_json_ld": raw_json})
            self._json_ld_parts = None

        if normalized_tag in {"script", "style", "template", "noscript"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        if normalized_tag == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)
        if self._h1_parts is not None:
            self._h1_parts.append(data)
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)
        if self._in_body and self._hidden_depth == 0:
            self.visible_text_parts.append(data)


def _collect_json_ld_types(value: Any) -> list[str]:
    collected: list[str] = []
    if isinstance(value, dict):
        raw_type = value.get("@type")
        if isinstance(raw_type, str) and raw_type.strip():
            collected.append(raw_type.strip())
        elif isinstance(raw_type, list):
            collected.extend(str(item).strip() for item in raw_type if str(item).strip())
        for nested_value in value.values():
            collected.extend(_collect_json_ld_types(nested_value))
    elif isinstance(value, list):
        for item in value:
            collected.extend(_collect_json_ld_types(item))
    return collected


def parse_html_signals(html: str) -> SeoHtmlSignals:
    parser = _SeoHtmlParser()
    parser.feed(html)
    parser.close()

    json_ld_types: list[str] = []
    for document in parser.json_ld_documents:
        json_ld_types.extend(_collect_json_ld_types(document))

    return SeoHtmlSignals(
        title=parser.title,
        description=parser.description,
        canonical=parser.canonical,
        robots=parser.robots,
        h1=tuple(parser.h1_values),
        json_ld_types=tuple(dict.fromkeys(json_ld_types)),
        internal_links=tuple(dict.fromkeys(parser.internal_links)),
        visible_text=normalize_visible_text(" ".join(parser.visible_text_parts)),
    )
