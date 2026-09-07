"""Export a scenario's material section to a local preparation file; no upload or LLM call."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

MATERIALS_HEADING = "## 서비스에 등록할 자료"
QUESTIONS_HEADING = "## 시험 질문과 확인 기준"
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")

# Evaluation preparation constraint only: never import this list into Product runtime.
ALLOWED_EMAIL_ADDRESSES = frozenset({
    "jjssyy0527@gmail.com",
    "bonggyulim0728@gmail.com",
    "qhdrbdhkdwks2@gmail.com",
})
TEXT_MATERIAL_EXTENSIONS = frozenset({".md", ".txt", ".csv"})
EMAIL_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def validate_material_emails(text: str) -> None:
    """Check email tokens in these text assets; not a mail-header parser or send gate.

    Case is ignored, but plus-addresses and dotted aliases are not normalized to an
    allowed identity. This does not authorize any business action or network I/O.
    """
    invalid = sorted({m.group() for m in EMAIL_ADDRESS.finditer(text)
                      if m.group().casefold() not in ALLOWED_EMAIL_ADDRESSES})
    if invalid:
        raise ValueError("Unapproved email address in evaluation material: " + ", ".join(invalid))


def outside_fence_lines(text: str) -> list[tuple[int, str]]:
    """Read our Markdown's unquoted lines, respecting fence character and length.

    This is a bounded scanner for the workspace's headings/inline links, not a
    full Markdown renderer. A shorter fence cannot close a longer payload fence.
    """
    outside: list[tuple[int, str]] = []
    active: tuple[str, int] | None = None
    for index, line in enumerate(text.splitlines()):
        if active is not None:
            character, length = active
            if re.fullmatch(r" {0,3}" + re.escape(character) + "{" + str(length) + r",}[ \t]*", line):
                active = None
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            token, info = match.groups()
            if token[0] == "`" and "`" in info:
                raise ValueError("Invalid backtick fence info; inspect the source")
            active = (token[0], len(token))
        else:
            outside.append((index, line))
    if active is not None:
        raise ValueError("Unclosed code fence; inspect the source before exporting")
    return outside


def section_bounds(text: str) -> tuple[int, int]:
    outside = outside_fence_lines(text)
    indices = {heading: [i for i, line in outside if line.strip() == heading]
               for heading in (MATERIALS_HEADING, QUESTIONS_HEADING)}
    if any(len(value) != 1 for value in indices.values()):
        raise ValueError("Exactly one materials section and one question section are required")
    start, end = indices[MATERIALS_HEADING][0], indices[QUESTIONS_HEADING][0]
    if end <= start:
        raise ValueError("Question section must follow materials")
    for i, line in outside:
        if start < i < end and (
            re.match(r"^ {0,3}#{1,2}\s", line)
            or line.strip().startswith(("**평가자 확인", "**사용자 입력", "### 질문 "))
        ):
            raise ValueError("Unexpected section/evaluation label inside materials")
    return start, end


def extract_materials(text: str) -> str:
    """Include business material and preparation metadata, never question/answer sections."""
    validate_material_emails(text)
    start, end = section_bounds(text)
    body = "\n".join(text.splitlines()[start + 1:end]).strip()
    if not body:
        raise ValueError("Empty materials section")
    return ("# 등록 준비용 자료 — 아직 업로드하지 않음\n\n"
            "제목·발신·시간·상태·목록 등의 준비 메타정보와 본문을 구분한다. "
            "이 파일 전체를 하나의 메일/Issue 본문으로 올리지 않는다.\n\n" + body + "\n")


def relocate_links(text: str, source: Path, root: Path, output_parent: Path) -> str:
    """Rebase existing local links only; do not copy files or rewrite business payloads."""
    lines = text.splitlines()
    for index, line in outside_fence_lines(text):
        def rebase(match: re.Match[str]) -> str:
            target = match.group(1)
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or target.startswith("#"):
                return match.group(0)
            destination = (source.parent / unquote(parts.path)).resolve(strict=True)
            if not destination.is_relative_to(root.resolve()):
                raise ValueError(f"Local material link leaves workspace: {target}")
            if not destination.is_file():
                raise ValueError(f"Local material link is not a file: {target}")
            if destination.suffix.lower() in TEXT_MATERIAL_EXTENSIONS:
                validate_material_emails(destination.read_text(encoding="utf-8-sig"))
            try:
                relative = os.path.relpath(destination, output_parent.resolve())
                url = quote(Path(relative).as_posix(), safe="/-._~")
            except ValueError:  # Different Windows drives: retain a valid local file URI.
                url = destination.as_uri()
            if parts.query:
                url += "?" + parts.query
            if parts.fragment:
                url += "#" + quote(unquote(parts.fragment), safe="-._~")
            return match.group(0).replace("(" + target + ")", "(" + url + ")", 1)
        lines[index] = LINK.sub(rebase, line)
    return "\n".join(lines) + "\n"


def read_scenario(path: Path, root: Path | None = None, *, output_parent: Path | None = None) -> str:
    root = (root or Path(__file__).resolve().parent).resolve()
    allowed = (root / "datasets").resolve(strict=True)
    actual = path.resolve(strict=True)
    if (not allowed.is_relative_to(root) or not actual.is_relative_to(allowed)
            or not actual.is_file() or actual.suffix.lower() != ".md"):
        raise ValueError("Only Markdown scenarios inside datasets/ may be exported")
    value = extract_materials(actual.read_text(encoding="utf-8"))
    return relocate_links(value, actual, root, output_parent or actual.parent)


def export_to_file(scenario: Path, output: Path, root: Path | None = None) -> None:
    value = read_scenario(scenario, root, output_parent=output.parent)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, help="New local file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        if args.output is None:
            print(read_scenario(args.scenario), end="")
        else:
            export_to_file(args.scenario, args.output)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"Export refused: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
