"""CLI for the canonical Evaluation-owned Prompt candidate materializer."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation.prompt_candidate import PromptCandidateError, materialize_prompt_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument(
        "--keep-extra-product-slots", action="store_true",
        help="Keep additional current Product Prompt sources unchanged in the DRAFT copy.",
    )
    args = parser.parse_args()

    candidate_dir = Path(__file__).resolve().parent
    repository_root = (
        args.repository_root.resolve()
        if args.repository_root is not None
        else candidate_dir.parents[2]
    )
    try:
        result = materialize_prompt_candidate(
            candidate_path=candidate_dir / "candidate.json",
            repository_root=repository_root,
            output_dir=args.output,
            keep_extra_product_slots=args.keep_extra_product_slots,
        )
    except PromptCandidateError as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"DRAFT copy: {result.output_dir}")
    print("NOT TESTED: current caller semantics, schema payloads, model quality, or activation.")


if __name__ == "__main__":
    main()
