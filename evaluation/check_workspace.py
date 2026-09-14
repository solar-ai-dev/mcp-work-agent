"""Offline document integrity only: not a semantic grader, Prompt activation, or Live test."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

from export_materials import (
    LINK,
    TEXT_MATERIAL_EXTENSIONS,
    extract_materials,
    outside_fence_lines,
    section_bounds,
    validate_material_emails,
)


PROMPT_ROOT = Path("prompt_candidates/mcp-tool-use-2026-v1")
LEGACY_ROOT = Path("prompt_candidates/planning-review-sllm-decomposition-v0.9.2")


def prompt_asset_errors(root: Path) -> list[str]:
    """Check packaged Prompt identities/hashes, not external Product compatibility."""
    failures: list[str] = []
    current = root / PROMPT_ROOT
    if not current.exists():
        return failures
    if (root / "prompts").exists():
        failures.append("Duplicate moved Prompt root evaluation/prompts exists")
    try:
        from prompt_candidate import load_prompt_candidate
        bundle = load_prompt_candidate(current, repository_root=root.parent)
        actual = {p.stem for p in (current / "sources").glob("*.md")}
        if actual != set(bundle.source_hashes):
            failures.append("Packaged Prompt source/slot set mismatch")
        for slot, row in bundle.payload["sources"].items():
            if row["source"] != f"sources/{slot}.md":
                failures.append(f"Original Prompt filename/slot binding changed: {slot}")
        for script in (root / "prompt_candidate.py", current / "materialize_prompt_candidate.py"):
            if not script.is_file():
                failures.append(f"Missing original Prompt materializer: {script.name}")
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        failures.append(f"Prompt candidate integrity: {error}")

    legacy = root / LEGACY_ROOT
    for manifest in ("prompt-manifest-v0.9.1.json", "prompt-manifest-v0.9.2-candidate.json"):
        try:
            doc = json.loads((legacy / manifest).read_text(encoding="utf-8"))
            for slot in doc["slots"]:
                paths = [root.parent / name for name in [*slot["files"], slot["assembled_path"]]]
                if any(not q.resolve().is_relative_to(legacy.resolve()) for q in paths):
                    raise ValueError("Prompt path leaves original candidate directory")
                content = paths[-1].read_bytes()
                if b"".join(q.read_bytes() for q in paths[:-1]) != content:
                    raise ValueError(f"source/assembled mismatch: {slot['slot_id']}")
                digest = hashlib.sha256(content).hexdigest()
                if digest != slot["content_hash"] or digest != slot["assembled_hash"]:
                    raise ValueError(f"assembled hash mismatch: {slot['slot_id']}")
                if slot["activation_status"] != "DRAFT":
                    raise ValueError(f"unexpected activated legacy slot: {slot['slot_id']}")
            contract = root.parent / doc["runtime_input_contract"]
            if not contract.resolve().is_relative_to(legacy.resolve()) or not contract.is_file():
                raise ValueError("Legacy input contract missing or moved")
        except (OSError, ValueError, TypeError, KeyError) as error:
            failures.append(f"{manifest}: {error}")
    return failures


def heading_anchors(text: str) -> set[str]:
    """Anchors for the simple ATX headings used here, including duplicate suffixes."""
    counts: Counter[str] = Counter()
    anchors: set[str] = set()
    for _, line in outside_fence_lines(text):
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            base = re.sub(r"[^\w\s-]", "", match.group(1).lower(), flags=re.UNICODE)
            base = re.sub(r"\s", "-", base)
            occurrence = counts[base]
            anchors.add(base if occurrence == 0 else f"{base}-{occurrence}")
            counts[base] += 1
    return anchors


def check_workspace(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    if not root.is_dir() or not (root / "README.md").is_file():
        return ["Workspace directory and README.md are required"]
    identities: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError("Document symlink leaves workspace")
            text = path.read_text(encoding="utf-8")
            plain_lines = outside_fence_lines(text)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{relative}: {error}")
            continue
        if not text.startswith("# ") and not (path.is_relative_to(root / LEGACY_ROOT) and path.name != "README.md"):
            errors.append(f"{relative}: missing document title")
        plain = "\n".join(line for _, line in plain_lines)
        for match in LINK.finditer(plain):
            target = match.group(1)
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                continue  # Offline check does not assert that external links work.
            destination = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            if not destination.is_relative_to(root):
                errors.append(f"{relative}: link leaves workspace: {target}")
            elif not destination.exists():
                errors.append(f"{relative}: broken local link: {target}")
            elif parts.fragment and destination.suffix.lower() == ".md":
                try:
                    anchors = heading_anchors(destination.read_text(encoding="utf-8"))
                    if unquote(parts.fragment) not in anchors:
                        errors.append(f"{relative}: broken heading anchor: {target}")
                except (OSError, UnicodeError, ValueError) as error:
                    errors.append(f"{relative}: unreadable link destination: {error}")
        if path.parent == root / "datasets":
            try:
                extract_materials(text)
                _, end = section_bounds(text)
                questions = [(i, line) for i, line in plain_lines
                             if i > end and re.match(r"^### 질문 \d+", line)]
                numbers = [int(re.match(r"^### 질문 (\d+)", line).group(1)) for _, line in questions]
                if numbers != list(range(1, len(numbers) + 1)):
                    errors.append(f"{relative}: question numbers must be unique and sequential")
                for offset, (i, line) in enumerate(questions):
                    stop = questions[offset + 1][0] if offset + 1 < len(questions) else len(text.splitlines())
                    block = "\n".join(value for n, value in plain_lines if i < n < stop)
                    if "**사용자 입력**" not in block or "**평가자 확인 — 제품 입력에 넣지 않음**" not in block:
                        errors.append(f"{relative}: missing question/evaluator boundary after {line}")
            except ValueError as error:
                errors.append(f"{relative}: {error}")
        # Detect duplicate navigation identities in headings, not citations or malicious payloads.
        if path.parent in (root / "datasets", root / "checks"):
            for _, line in plain_lines:
                if line.startswith("### "):
                    for identity in re.findall(r"(?:CASE-(?:CORE|HOLDOUT|STRESS)-\d+|SQ-(?:DEV|HOLDOUT)-\d+|EPV-\d+)", line):
                        if identity in identities:
                            errors.append(f"{relative}: duplicate question identity {identity} ({identities[identity]})")
                        identities[identity] = str(relative)
        if path.parent == root / PROMPT_ROOT / "sources":
            for heading in ("## Responsibility", "## Input boundary", "## Decision procedure", "## Boundaries", "## Output and repair"):
                if sum(line.strip() == heading for _, line in plain_lines) != 1:
                    errors.append(f"{relative}: require exactly one {heading}")
            if re.search(r"(?:CASE-(?:CORE|HOLDOUT|STRESS)-\d+|SQ-(?:DEV|HOLDOUT)-\d+|FW-D-\d+)", text):
                errors.append(f"{relative}: dataset identity in internal Prompt")
    for folder in (root / "datasets", root / "checks"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_MATERIAL_EXTENSIONS:
                try:
                    if not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("Email-check asset leaves workspace")
                    validate_material_emails(path.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, ValueError) as error:
                    errors.append(f"{path.relative_to(root)}: {error}")
    errors.extend(prompt_asset_errors(root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    failures = check_workspace(parser.parse_args().root)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: UTF-8, section/fence boundaries, question identities, local links/anchors, Prompt separation, three-account email scope, original Prompt paths/source/assembled/bundle hashes.")
    print("NOT TESTED: business semantics, external URLs, upload, runtime/schema compatibility, models, or Live behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
