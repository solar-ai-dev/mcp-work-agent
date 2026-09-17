"""Evaluation-only BM25 result accounting; no product runtime dependency on BM25."""

from __future__ import annotations

import pytest
from scripts.evaluate_direct_bm25_search import _common_corpus, _positions, _rrf
from scripts.evaluate_empty_gmail_search_hypothesis import _quoted_query

from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import _clean_terms


def test_common_corpus_uses_all_snapshot_packs_without_duplicate_segments() -> None:
    segments, summary = _common_corpus()

    assert summary["resource_pack_count"] == 26
    assert summary["unique_resource_version_count"] == 103
    assert summary["segment_count"] == len(segments) == 106
    assert len({segment.segment_id for segment in segments}) == len(segments)
    assert {segment.source for segment in segments} == {"GMAIL", "TASKS", "CALENDAR"}


def test_optional_langchain_direct_retrieval_uses_common_documents() -> None:
    pytest.importorskip("rank_bm25")
    retrievers = pytest.importorskip("langchain_community.retrievers.bm25")
    documents = pytest.importorskip("langchain_core.documents")
    segments, _ = _common_corpus()
    retriever = retrievers.BM25Retriever.from_documents(
        [
            documents.Document(
                page_content=segment.text,
                metadata={"segment_id": segment.segment_id},
            )
            for segment in segments
        ],
        preprocess_func=_clean_terms,
        bm25_params={"k1": 1.2, "b": 0.75, "epsilon": 0.25},
        k=12,
    )

    found = retriever.invoke("Atlas 출고일")

    assert len(found) == 12
    assert all(item.page_content for item in found)
    assert all(item.metadata["segment_id"] for item in found)


def test_zero_bm25_score_does_not_count_as_target_hit_or_fused_candidate() -> None:
    first = [
        {"segment_id": "good", "resource_id": "target", "bm25_score": 2.0},
        {"segment_id": "zero", "resource_id": "missing", "bm25_score": 0.0},
    ]
    second = [
        {"segment_id": "good", "resource_id": "target", "bm25_score": 1.0},
        {"segment_id": "other", "resource_id": "other", "bm25_score": 0.5},
    ]

    assert _positions(first, ["target", "missing"], 4) == {
        "target": 1,
        "missing": None,
    }
    assert [item["segment_id"] for item in _rrf([first, second])] == ["good", "other"]


def test_outer_quote_is_formatting_only_but_embedded_gmail_syntax_is_rejected() -> None:
    assert _quoted_query('"Delta Plus 포장 승인"') == '"Delta Plus 포장 승인"'
    assert _quoted_query("Delta Plus 포장 승인") == '"Delta Plus 포장 승인"'
    for value in ('Delta "Plus"', "Delta\\Plus", "Delta\nPlus", '""'):
        try:
            _quoted_query(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid Gmail literal was accepted: {value!r}")
