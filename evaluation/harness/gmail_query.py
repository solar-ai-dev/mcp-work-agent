"""Small query-sensitive Gmail grammar for the synthetic evaluation provider."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

GmailPredicate = Callable[[Mapping[str, Any]], bool]


def compile_gmail_query(query: str) -> GmailPredicate:
    """Compile the provider subset emitted by the production Gmail projection."""

    tokens = re.findall(r'\{|\}|\(|\)|[^\s{}()"]*"(?:\\.|[^"\\])*"|[^\s{}()"]+', query)
    if re.sub(r"\s+", "", "".join(tokens)) != re.sub(r"\s+", "", query):
        raise ValueError("unsupported Gmail query syntax")
    index = 0

    def expression(closing: str | None = None, *, any_mode: bool = False) -> GmailPredicate:
        nonlocal index
        conjunctions: list[list[GmailPredicate]] = [[]]
        while index < len(tokens) and tokens[index] != closing:
            token = tokens[index]
            index += 1
            if token in {"}", ")"}:
                raise ValueError("unbalanced Gmail query")
            if token == "OR":
                if not conjunctions[-1]:
                    raise ValueError("empty Gmail OR branch")
                conjunctions.append([])
                continue
            predicate = (
                expression("}" if token == "{" else ")", any_mode=token == "{")
                if token in {"{", "("}
                else _term(token)
            )
            if any_mode and conjunctions[-1]:
                conjunctions.append([])
            conjunctions[-1].append(predicate)
        if closing is not None:
            if index == len(tokens):
                raise ValueError("unclosed Gmail query group")
            index += 1
        if not conjunctions[-1] and (closing is not None or len(conjunctions) > 1):
            raise ValueError("empty Gmail query branch")
        return lambda resource: any(
            all(predicate(resource) for predicate in group) for group in conjunctions
        )

    predicate = expression()
    if index != len(tokens):
        raise ValueError("Gmail query contains trailing tokens")
    return predicate


def _term(token: str) -> GmailPredicate:
    negate = token.startswith("-")
    token = token[1:] if negate else token
    operator, separator, raw_value = token.partition(":")
    if not separator:
        operator, raw_value = "text", token
    if operator not in {
        "text",
        "subject",
        "from",
        "to",
        "cc",
        "bcc",
        "after",
        "before",
        "in",
        "is",
        "label",
        "rfc822msgid",
    }:
        raise ValueError(f"unsupported Gmail query operator: {operator}")
    value = raw_value.strip('"').replace('\\"', '"').casefold()
    if not value:
        raise ValueError("empty Gmail query term")
    boundary = None
    if operator in {"after", "before"}:
        boundary = int(value) if value.isdecimal() else datetime.fromisoformat(value).timestamp()

    def matches(resource: Mapping[str, Any]) -> bool:
        messages = _messages(resource)
        if operator in {"after", "before"}:
            assert boundary is not None
            stamps = [
                datetime.fromisoformat(timestamp).timestamp()
                for message in messages
                for timestamp in (message.get("received_at"),)
                if isinstance(timestamp, str)
            ]
            result = any(
                stamp >= boundary if operator == "after" else stamp < boundary
                for stamp in stamps
            )
        elif operator in {"in", "is", "label"}:
            labels = {
                str(label).casefold()
                for label in resource.get("label_ids", ["INBOX"])
            }
            normalized = "draft" if value == "drafts" else value
            result = normalized not in labels if value == "read" else normalized in labels
        elif operator == "subject":
            result = value in str(resource.get("subject", "")).casefold()
        elif operator == "rfc822msgid":
            result = any(
                value == str(message.get("rfc822_message_id", "")).casefold()
                for message in messages
            )
        elif operator in {"from", "to", "cc", "bcc"}:
            fields = {
                "from": ("sender_email", "sender_name"),
                "to": ("recipients", "to"),
                "cc": ("cc",),
                "bcc": ("bcc",),
            }[operator]
            result = any(
                value in str(message.get(field, "")).casefold()
                for message in messages
                for field in fields
            )
        else:
            text = [str(resource.get("subject", "")), str(resource.get("participants", ""))]
            for message in messages:
                text.extend(
                    str(message.get(field, ""))
                    for field in (
                        "subject",
                        "body",
                        "sender_name",
                        "sender_email",
                        "recipients",
                        "to",
                        "cc",
                    )
                )
            result = value in " ".join(text).casefold()
        return not result if negate else result

    return matches


def _messages(resource: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = resource.get("messages", [])
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


__all__ = ["compile_gmail_query"]
