"""Shared query-sensitive synthetic Provider boundary; never consumes questions or Gold."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


class RetrievalCorpus:
    """Search one shared Gmail world using a deliberately bounded provider grammar."""

    def __init__(self, paths: list[Path], *, page_size: int = 3) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.page_size = page_size
        self.threads: dict[str, dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        for path in paths:
            source = json.loads(path.read_text(encoding="utf-8"))
            if set(source) != {"schema_version", "threads"}:
                raise ValueError("corpus accepts Provider resources only")
            for thread in source["threads"]:
                identity = thread["thread_id"]
                if identity in self.threads:
                    raise ValueError("duplicate corpus resource identity")
                self.threads[identity] = deepcopy(thread)

    def search(self, query: str, page_token: str | None = None) -> dict[str, Any]:
        predicate = _parse_query(query)
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        offset = 0
        if page_token is not None:
            bound_hash, raw_offset = page_token.split(":", 1)
            if bound_hash != query_hash or not raw_offset.isdecimal():
                raise ValueError("page token belongs to a different query")
            offset = int(raw_offset)
        # Provider ordering is independent of questions and Gold. Newer noise can
        # occupy the first page; details are not returned by candidate discovery.
        matches = [
            t
            for t in self.threads.values()
            if any(
                predicate(
                    {
                        **t,
                        "messages": [message],
                        "participants": [
                            message["sender"],
                            *message.get("to", []),
                            *message.get("cc", []),
                        ],
                    }
                )
                for message in t["messages"]
            )
        ]
        matches.sort(key=lambda t: max(m["sent_at"] for m in t["messages"]), reverse=True)
        selected = matches[offset : offset + self.page_size]
        continuation = offset + len(selected)
        result = {
            "threads": [
                {
                    "thread_id": t["thread_id"],
                    "subject": t["subject"],
                    "participants": t["participants"],
                }
                for t in selected
            ],
            "next_page_token": f"{query_hash}:{continuation}"
            if continuation < len(matches)
            else None,
        }
        self.calls.append(
            {
                "operation": "SEARCH" if page_token is None else "NEXT_PAGE",
                "query": query,
                "page_token": page_token,
                "status": "SUCCESS",
                "result_refs": [t["thread_id"] for t in selected],
            }
        )
        return result

    def detail(self, thread_id: str) -> dict[str, Any]:
        if thread_id not in self.threads:
            raise KeyError(thread_id)
        self.calls.append(
            {
                "operation": "DETAIL",
                "resource_ref": thread_id,
                "status": "SUCCESS",
                "result_refs": [thread_id],
            }
        )
        return deepcopy(self.threads[thread_id])


def _parse_query(query: str) -> Any:
    # AND by adjacency, bounded OR groups, phrases and provider field operators.
    tokens = re.findall(r'\{|\}|\(|\)|[^\s{}()"]*"(?:\\.|[^"\\])*"|[^\s{}()"]+', query)
    if re.sub(r"\s+", "", "".join(tokens)) != re.sub(r"\s+", "", query):
        raise ValueError("unsupported query syntax")
    index = 0

    def expression(closing: str | None = None, any_mode: bool = False) -> Any:
        nonlocal index
        conjunctions: list[list[Any]] = [[]]
        while index < len(tokens) and tokens[index] != closing:
            token = tokens[index]
            index += 1
            if token in {"}", ")"}:
                raise ValueError("unbalanced query")
            if token == "OR":
                if not conjunctions[-1]:
                    raise ValueError("empty OR branch")
                conjunctions.append([])
                continue
            if token in {"{", "("}:
                predicate = expression("}" if token == "{" else ")", token == "{")
            else:
                predicate = _term(token)
            if any_mode and conjunctions[-1]:
                conjunctions.append([])
            conjunctions[-1].append(predicate)
        if closing is not None:
            if index == len(tokens):
                raise ValueError("unclosed query group")
            index += 1
        if not conjunctions[-1] and (closing is not None or len(conjunctions) > 1):
            raise ValueError("empty query branch")
        return lambda thread: any(all(p(thread) for p in group) for group in conjunctions)

    return expression()


def _term(token: str) -> Any:
    negate = token.startswith("-")
    token = token[1:] if negate else token
    operator, separator, value = token.partition(":")
    if not separator:
        operator, value = "text", token
    if operator not in {"text", "subject", "from", "to", "cc", "bcc", "after", "before",
                        "in", "is", "label"}:
        raise ValueError(f"unsupported provider operator: {operator}")
    value = value.strip('"').replace('\\"', '"').casefold()
    if not value:
        raise ValueError("empty provider term")
    if operator in {"in", "is", "label"} and value not in {
        "inbox", "sent", "draft", "drafts", "unread", "read", "trash", "spam",
    }:
        raise ValueError("unsupported provider label")
    boundary = None
    if operator in {"after", "before"}:
        boundary = int(value) if value.isdecimal() else datetime.fromisoformat(value).timestamp()

    def matches(thread: dict[str, Any]) -> bool:
        if operator in {"after", "before"}:
            assert boundary is not None
            stamps = [datetime.fromisoformat(m["sent_at"]).timestamp() for m in thread["messages"]]
            result = any(t >= boundary if operator == "after" else t < boundary for t in stamps)
        elif operator in {"in", "is", "label"}:
            # Legacy shared corpus models received/read inbox mail unless the
            # resource explicitly supplies labels; never infer labels from a case.
            labels = {str(label).casefold() for label in thread.get("label_ids", ["INBOX"])}
            result = ("unread" not in labels if value == "read" else
                      ("draft" if value == "drafts" else value) in labels)
        elif operator == "subject":
            result = value in thread["subject"].casefold()
        elif operator in {"from", "to", "cc", "bcc"}:
            field = "sender" if operator == "from" else operator
            values = [m.get(field, []) for m in thread["messages"]]
            result = any(value in str(v).casefold() for v in values)
        else:
            text = [thread["subject"], *thread["participants"]]
            for message in thread["messages"]:
                text.extend([message["body"], message["sender"], message.get("sender_name", "")])
                text.extend(message.get("to", []) + message.get("cc", []))
            result = value in " ".join(text).casefold()
        return not result if negate else result

    return matches
