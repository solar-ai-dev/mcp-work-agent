"""Negative controls for the existing grader's optional search-strategy contract."""

from copy import deepcopy
from pathlib import Path

import pytest
from evaluation.dataset import load_case, load_jsonl
from evaluation.grader import grade_case
from tests.support.fakes.retrieval_corpus import RetrievalCorpus

ROOT = Path(__file__).parents[2]
DATA = ROOT / "evaluation/datasets/retrieval/query_strategy"


def observation():
    return {
        "final_answer": "9월 4일 오후 2시로 정정됐습니다.",
        "evidence_resource_refs": ["SQ-101"],
        "semantic_constraints": ["오로라", "김대리", "EVENT_TIME"],
        "resolved_identities": {"김대리": "haneul.kim@example.test"},
        "terminal_state": "COMPLETED",
        "terminal_result_kind": "SUCCESS",
        "interactions": [],
        "actions": [],
        "durable_effects": [],
        "query_trajectory": [
            {
                "operation": "SEARCH",
                "constraints": ["오로라", "김대리"],
                "reason_codes": ["USER_REQUEST"],
                "required_information": ["행사 날짜"],
                "provider_query": '오로라 "김대리"',
                "observation_refs": [],
            }
        ],
        "provider_calls": [
            {
                "connector_id": "google_workspace",
                "tool": "gmail_search_threads",
                "arguments": {"query": '오로라 "김대리"'},
                "operation": "SEARCH",
                "status": "SUCCESS",
                "result_refs": ["SQ-101"],
            }
        ],
    }


def reasons(case, observed):
    return {
        reason for result in grade_case(case, observed).results for reason in result.reason_codes
    }


def test_retrieval_grade__grounded_control__passes():
    assert grade_case(load_case("SQ-DEV-001", DATA / "cases.jsonl"), observation()).passed


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("identity", "IDENTITY_NOT_GROUNDED"),
        ("date", "REQUIRED_FACT_MISSING"),
        ("evidence", "ANSWER_REQUIRED_EVIDENCE_MISSING"),
        ("wrong_evidence", "WRONG_EVIDENCE_SELECTED"),
        ("terminal", "RETRIEVAL_TERMINATION_MISMATCH"),
        ("duplicate", "REPEATED_PROVIDER_CALL"),
        ("anchor", "EXACT_ANCHOR_LOST"),
        ("temporal_lowering", "EVENT_TIME_LOWERED_TO_MESSAGE_TIME"),
        ("changed", "CHANGED_HYPOTHESIS_WITHOUT_OBSERVATION"),
        ("trajectory", "QUERY_TRAJECTORY_MISSING"),
        ("purpose", "SEARCH_PURPOSE_OR_SUCCESS_CRITERIA_MISSING"),
    ],
)
def test_retrieval_grade__mutated_observation__fails(mutation, expected):
    observed = observation()
    if mutation == "identity":
        observed["resolved_identities"] = {"김대리": "bada.kim@example.test"}
    elif mutation == "date":
        observed["final_answer"] = "9월 2일로 확정됐습니다."
    elif mutation == "evidence":
        observed["evidence_resource_refs"] = []
    elif mutation == "wrong_evidence":
        observed["evidence_resource_refs"].append("SQ-103")
    elif mutation == "terminal":
        observed["terminal_result_kind"] = "PARTIAL"
    elif mutation == "duplicate":
        observed["provider_calls"] *= 2
    elif mutation == "anchor":
        observed["query_trajectory"][0]["constraints"] = ["김대리"]
    elif mutation == "temporal_lowering":
        observed["query_trajectory"][0]["provider_query"] += " after:1788188400"
    elif mutation == "changed":
        observed["query_trajectory"].append(deepcopy(observed["query_trajectory"][0]))
    elif mutation == "trajectory":
        observed["query_trajectory"] = []
    else:
        observed["query_trajectory"][0]["reason_codes"] = []
    assert expected in reasons(load_case("SQ-DEV-001", DATA / "cases.jsonl"), observed)


def test_retrieval_grade__provider_failure__is_not_normal_empty():
    case = load_case("SQ-DEV-006", DATA / "cases.jsonl")
    observed = observation()
    observed["provider_calls"][0].update(status="FAILURE", result_refs=[])
    assert "PROVIDER_FAILURE_AS_NO_RESULT" in reasons(case, observed)


def test_retrieval_grade__confirmation_without_candidate_evidence__fails():
    case = load_case("SQ-DEV-003", DATA / "cases.jsonl")
    observed = observation()
    observed.update(
        terminal_state="WAITING_CONFIRMATION", final_answer="", evidence_resource_refs=[]
    )
    assert "ANSWER_REQUIRED_EVIDENCE_MISSING" in reasons(case, observed)
    observed["evidence_resource_refs"] = ["SQ-101", "SQ-102"]
    assert "ANSWER_REQUIRED_EVIDENCE_MISSING" not in reasons(case, observed)


@pytest.mark.parametrize("wrong_role", [False, True])
def test_retrieval_grade__project_as_sender__rejects_accidentally_matching_query(wrong_role):
    case = load_case("SQ-DEV-003", DATA / "cases.jsonl")
    observed = observation()
    observed["semantic_constraints"] = [
        {"kind": "USER_REQUIREMENT", "field": "search_terms", "value": ["오로라"]},
        {"kind": "PERSON", "field": "person", "value": ["김대리"]},
        {"kind": "PERSON", "field": "sender", "value": ["김대리"]},
    ]
    if wrong_role:
        observed["semantic_constraints"] = [
            {"kind": "PERSON", "field": "person", "value": ["김대리"]},
            {"kind": "PERSON", "field": "sender", "value": ["오로라"]},
        ]
    assert ("SEMANTIC_CONSTRAINT_ROLE_MISMATCH" in reasons(case, observed)) is wrong_role


def test_retrieval_grade__empty_detail__does_not_prove_search_no_result():
    case = load_case("SQ-DEV-006", DATA / "cases.jsonl")
    observed = observation()
    observed["provider_calls"][0].update(operation="DETAIL", result_refs=[])
    assert "NO_RESULT_WITHOUT_SUCCESSFUL_SEARCH" in reasons(case, observed)


def test_retrieval_grade__excluded_container__fails_safety_gate():
    case = load_case("SQ-DEV-001", DATA / "cases.jsonl")
    case["retrieval_gold"]["allowed_containers"] = ["calendar:allowed"]
    observed = observation()
    observed["provider_calls"][0]["container_ref"] = "calendar:excluded"
    grade = grade_case(case, observed)
    assert not grade.hard_gate_passed
    assert "RESOURCE_ALLOWLIST_VIOLATION" in reasons(case, observed)


def test_shared_corpus__query_fields_and_pages__produce_different_results():
    corpus = RetrievalCorpus([DATA / "corpus_extension.json"], page_size=2)
    broad = corpus.search("오로라")
    page = corpus.search("오로라", broad["next_page_token"])
    assert broad["threads"] != page["threads"]
    assert all("messages" not in row for row in broad["threads"])
    sender = corpus.search("from:haneul.kim@example.test")
    recipient = corpus.search("to:haneul.kim@example.test")
    assert {row["thread_id"] for row in sender["threads"]} == {"SQ-101", "SQ-106"}
    assert {row["thread_id"] for row in recipient["threads"]} == {"SQ-104"}
    assert corpus.search('subject:"존재하지 않는 제목"')["threads"] == []
    assert len(corpus.detail("SQ-101")["messages"]) == 3
    assert corpus.search('"9월 4일"')["threads"][0]["thread_id"] == "SQ-101"
    with pytest.raises(ValueError, match="different query"):
        corpus.search("다른 검색", broad["next_page_token"])
    with pytest.raises(ValueError, match="unsupported"):
        corpus.search("made_up_operator:value")


def test_shared_corpus__gold_file__cannot_be_provider_input():
    with pytest.raises((ValueError, KeyError)):
        RetrievalCorpus([DATA / "corpus_manifest.json"])
    rows = load_jsonl(DATA / "cases.jsonl")
    dev = {r["scenario_family_id"] for r in rows if r["split"] == "DEV"}
    holdout = {r["scenario_family_id"] for r in rows if r["split"] == "HOLDOUT"}
    assert dev.isdisjoint(holdout)


def test_retrieval_grade__resource_only_gold__does_not_pass_empty_evidence():
    case = {
        "requested_outcome": "ANSWER",
        "required_resource_ids": ["required"],
        "end_state_gold": {"terminal_expectation": "COMPLETED"},
    }
    assert "ANSWER_REQUIRED_EVIDENCE_MISSING" in reasons(
        case, {"final_answer": "Unsupported answer", "terminal_state": "COMPLETED"}
    )


def test_retrieval_grade__exact_identity_followup__preserves_resolved_mention():
    observed = observation()
    observed["query_trajectory"][0]["constraints"] = ["오로라", "haneul.kim@example.test"]
    assert "EXACT_ANCHOR_LOST" not in reasons(
        load_case("SQ-DEV-001", DATA / "cases.jsonl"), observed
    )


def test_retrieval_grade__title_discovery__must_not_regress_after_exact_identity():
    case = load_case("SQ-DEV-001", DATA / "cases.jsonl")
    observed = observation()
    observed["query_trajectory"][0]["constraints"] = ["오로라", "대리"]
    assert "EXACT_ANCHOR_LOST" not in reasons(case, observed)
    exact = deepcopy(observed["query_trajectory"][0])
    exact.update(constraints=["오로라", "haneul.kim@example.test"], observation_refs=["prior"])
    fuzzy = deepcopy(observed["query_trajectory"][0])
    fuzzy["observation_refs"] = ["prior-exact"]
    observed["query_trajectory"].extend([exact, fuzzy])
    assert "EXACT_ANCHOR_LOST" in reasons(case, observed)


def test_retrieval_grade__original_request_only__does_not_prove_constraints_preserved():
    observed = observation()
    observed["semantic_constraints"] = [{"field": "original_search_request",
                                         "value": "오로라 김대리 EVENT_TIME"}]
    assert "REQUEST_CONSTRAINT_LOST" in reasons(
        load_case("SQ-DEV-001", DATA / "cases.jsonl"), observed,
    )


def test_shared_corpus__participant_time_conjunction__matches_same_message():
    corpus = RetrievalCorpus([DATA / "corpus_extension.json"])
    # The coordinator's message is before Aug 25; a later message in the same
    # thread must not satisfy this sender+received-time query for them.
    assert corpus.search("from:coordinator@example.test after:1787612400")["threads"] == []


def test_shared_corpus__message_labels__are_provider_facts_not_question_answers():
    corpus = RetrievalCorpus([DATA / "corpus_extension.json"])
    assert corpus.search("in:inbox")["threads"]
    assert corpus.search("in:sent")["threads"] == []
    assert corpus.search("is:unread")["threads"] == []
    assert corpus.search("is:read")["threads"]
    with pytest.raises(ValueError):
        corpus.search("in:unsupported")
