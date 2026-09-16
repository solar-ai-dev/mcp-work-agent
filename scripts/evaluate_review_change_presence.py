"""Compare a presence-preserving proposal delta under the 026 output schema."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts import evaluate_review_resolution_output as resolution
from scripts.evaluate_review_proposal_transition import _proposal_transition


def _changed_values(previous: object, current: object, path: str = "") -> list[dict[str, Any]]:
    if isinstance(previous, dict) and isinstance(current, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(previous.keys() | current.keys()):
            nested = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in previous:
                result.append(
                    {
                        "path": nested,
                        "previous": {"present": False},
                        "current": {"present": True, "value": current[key]},
                    }
                )
            elif key not in current:
                result.append(
                    {
                        "path": nested,
                        "previous": {"present": True, "value": previous[key]},
                        "current": {"present": False},
                    }
                )
            else:
                result.extend(_changed_values(previous[key], current[key], nested))
        return result
    if previous == current:
        return []
    return [
        {
            "path": path,
            "previous": {"present": True, "value": previous},
            "current": {"present": True, "value": current},
        }
    ]


def _transition(case: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    transition = _proposal_transition(case, current)
    route_id = transition["route_id"]
    before_action = next(
        action for action in case["plan_before"]["actions"] if action["route_id"] == route_id
    )
    current_action = next(action for action in current["actions"] if action["route_id"] == route_id)
    transition["changed_arguments"] = _changed_values(
        before_action["arguments"], current_action["arguments"]
    )
    return transition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle", type=Path, required=True)
    parser.add_argument("--connected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resolution._proposal_transition = _transition
    resolution.evaluate(args.cycle, args.connected, args.output)


if __name__ == "__main__":
    main()
