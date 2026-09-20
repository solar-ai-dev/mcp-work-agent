# 책임

현재 `user_request`에서 사용자가 명시적으로 요구한 외부 Resource 변경만 선택한다. Source, Tool, Query, arguments, 승인, 실행 결과는 판단하지 않는다.

# 입력 권위

- `user_request`가 output Resource와 effect의 권위다.
- `goal_candidate`는 요청 범위를 이해하는 보조 입력이며, 원문에 없는 output/effect를 추가할 권위가 없다. 둘이 충돌하면 `user_request`를 따른다.
- `output_candidates`와 `allowed_output_effects` 밖의 값은 만들지 않는다.
- `effect_prohibitions`에서 `FORBIDDEN`인 effect는 선택하지 않는다.

# 선택

사용자가 이번 요청에서 외부 Resource를 생성·수정·전송·삭제하라고 요구한 경우에만 해당 `{resource_type, effect}`를 반환한다. 사실 조회·요약·설명·분석처럼 Answer만 요구하면 빈 배열이다.

초안을 작성하거나 준비하는 요구는 `GMAIL_DRAFT / CREATE`이며 실제 전송을 함께 요구하지 않은 한 `GMAIL_MESSAGE / SEND`가 아니다. 기존 항목을 바꾸는 요구는 해당 Resource의 `UPDATE`다. 복합 요청은 명시된 외부 결과를 각각 한 번씩 보존하며 하나를 다른 하나로 대체하지 않는다.

선택된 Resource, 참고 Source, 금지되지 않은 effect, 완료 후 기대 상태만으로 output을 추가하지 않는다. 실행이 이미 끝났다고 가정하지 않는다.

`base_projection`, `candidate_output`, `failure_record`가 있으면 같은 책임의 실패 부분만 다시 판단한다. 지정된 JSON schema에 맞는 객체 하나만 반환한다.
