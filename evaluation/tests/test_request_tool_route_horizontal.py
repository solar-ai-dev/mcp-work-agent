import pytest
from scripts.evaluate_request_tool_route_horizontal import _selected_case_ids


def test_all_canonical_selection_keeps_the_fixed_92_denominator() -> None:
    case_ids = _selected_case_ids(all_canonical=True, requested=None)

    assert len(case_ids) == 92
    assert case_ids[0] == "CASE-CORE-001"
    assert case_ids[-1] == "CASE-STRESS-020"


def test_all_canonical_cannot_be_combined_with_case_selection() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        _selected_case_ids(all_canonical=True, requested=["CASE-CORE-001"])
