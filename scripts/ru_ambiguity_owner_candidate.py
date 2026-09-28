"""v29: evaluation-only removal of global-count ambiguity decision shortcuts.

The source/Work binding, schema, owner, validator and input envelope are unchanged.
This is a deletion-only Prompt experiment, not another semantic rule or example.
"""

from __future__ import annotations

import hashlib

CANDIDATE_ID = "ambiguity-without-global-count-v29"
INPUT_MARKER = "Allowed current-Run input projection (JSON):\n"


def ambiguity_owner_instruction(instruction: str) -> str:
    """Fail closed if the Product paragraphs differ from the reviewed source."""
    source, separator, projection = instruction.partition(INPUT_MARKER)
    if not separator:
        raise ValueError("the assembled Product input marker is missing")
    start = "2. 먼저 다음 네 값만으로 source 대상이 결속됐는지 확인한다:"
    end = "4. 대상이 선택됐거나 검색 가능하고,"
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("the reviewed global-count decision block changed")
    first, rest = source.split(start, 1)
    _, tail = rest.split(end, 1)
    source = first + "2. 대상이 선택됐거나 검색 가능하고," + tail
    source = source.replace(
        "\n5. 사용자 선택과 Connector 조회 요구가", "\n3. 사용자 선택과 Connector 조회 요구가", 1
    )
    repeat = "target identity를 먼저 판정한 뒤에만 그 target의 속성 조회를 판정한다."
    boundary = "READ라는 이유만으로 판단을 생략하지 않고"
    if source.count(repeat) != 1 or source.count(boundary) != 1:
        raise ValueError("the reviewed repeated-count/example block changed")
    first, rest = source.split(repeat, 1)
    _, tail = rest.split(boundary, 1)
    source = first + boundary + tail
    return source + separator + projection


def candidate_source_hash(source: str) -> str:
    transformed = ambiguity_owner_instruction(source + INPUT_MARKER + "{}")
    return hashlib.sha256(transformed.partition(INPUT_MARKER)[0].encode()).hexdigest()
