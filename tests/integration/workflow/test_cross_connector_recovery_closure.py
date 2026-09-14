"""Production Graph regression with only external providers replaced by fixtures."""

from pathlib import Path

import pytest
from scripts.measure_recovery_restart import measure


@pytest.mark.parametrize(
    "connector,scenario",
    [
        ("github", "reauth_verification"),
        ("google_workspace", "cancel_after_write"),
        ("github", "lookup_unavailable"),
        ("google_workspace", "restart_approval"),
    ],
)
def test_production_graph__settles_recovery__without_repeated_write(
    tmp_path: Path,
    connector: str,
    scenario: str,
) -> None:
    result = measure(tmp_path, connector, scenario)
    assert result["measurement_status"] == "PASS"
    assert result["external_effect_count"] == 1
    assert len(result["attempts"]) == 1
