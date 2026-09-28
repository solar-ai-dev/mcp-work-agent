# 064 — Task/Calendar 필드 authority와 여러 Evidence chunk의 동일 객체 보존

기준 HEAD `be9469f1`. 실제 모델의 Source/Output 오판과 별개로, Task/Calendar의
결정적 답변·Draft 조립 consumer에서 재현 가능한 코드 결함을 수정했다.

## 최초 실패와 수정

기존 `project_task_read_answer._task_fields`와 Draft materializer의 `_fact_lines`는
Evidence excerpt를 줄 단위 `key: value`로 다시 파싱했다. 따라서 실제 Task가
`needsAction`이어도 notes의 `status: completed`가 상태를 덮어썼다. Calendar의
description도 title/start/end/status를 덮을 수 있었다. title 자체에 개행이 있으면
본문이 완전히 동일한 두 관측에서 실제 Provider 필드는 달라질 수 있어, 첫 값 우선이나
notes 이전까지만 파싱하는 방식으로는 해결되지 않는다.

수정 경계는 Retrieval의 관측 필드 보존 → 기존 Run-scoped snapshot store → Planning의
exact Evidence binding → 결정적 consumer다. 새 의미 판단이나 LLM 규칙을 추가하지 않았다.

- Task는 title/status/due/notes, Event는 title/start/end/timezone/status/location/description을
  allowlist로 보존한다. 기존 recovery marker 제거 후 visible 값, Resource type/handle/parent,
  Provider version을 canonical hash에 결속한다.
- 기존 normalization의 `max_segment_chars` 예산을 넘거나 타입이 잘못되면 부분 필드를
  저장하지 않는다. 생략·null·빈 문자열을 구분한다.
- locator에는 version ref만 추가하고 본문은 넣지 않는다. 같은 Run에서 선택된 Evidence의
  exact handle/version snapshot만 소비하며, unversioned/latest 추정은 금지한다.
- 과거 binding이 없거나 snapshot 누락·다른 Run·hash 불일치이면 결정적 경로가 None을
  반환해 기존 LLM 경로를 사용한다. 현재/과거 checkpoint를 재작성하지 않는다.
- normalized text/chunk version/segment ID는 불변이다. 기존 raw cache의 segment ID로
  rehydrate되는 직접 회귀를 추가했다. 신규 locator가 포함된 Evidence ID는 기존 hash 규칙을
  따르고 persisted Evidence ID를 소급 변환하지 않는다.
- 연결 리뷰에서 같은 Resource의 여러 chunk가 여러 Task/Event로 출력되는 기존 결함도
  확인했다. 같은 handle/version은 한 객체로 출력하되 citation refs는 모두 유지한다.
  같은 handle의 다른 version들이 함께 선택되면 임의 최신 선택 없이 기존 LLM 경로로 돌아간다.

Canonical05와 직접 producer/consumer/projection을 함께 정합화했다. 기존 Planning
`source_snapshots`의 사용 범위를 연결했으며 새로운 State/Port/Node/Edge는 만들지 않았다.
snapshot은 LLM Prompt에 추가하지 않는다. Approval/Policy/Identity/Execution/Verification과
Prompt·manifest·runtime·Dataset/Gold는 변경하지 않았다.

## 검증과 한계

- 직접 검사 **210 PASS**, 제품 14파일 scoped mypy PASS, 변경 22파일 Ruff PASS.
- 루트 인접 회귀 **1,782 PASS / 8.01초**, 단일 pytest 프로세스:
  `tests/unit/application/agents/{request_understanding,retrieval,planning}`,
  `tests/unit/adapters/langgraph`, `tests/architecture/langgraph`,
  `tests/architecture/prompt`, `tests/architecture/test_planning_review_owner_local_structure.py`.
  두 숫자는 겹치는 범위이므로 합산하지 않는다.
- 루트 리뷰에서 서로 다른 두 Task는 합치지 않고 TaskList citation을 제외하는 기존
  반례를 별도 보강했다. 해당 consumer 파일 **31 PASS**, Ruff PASS.
- 실제 Retrieval normalize physical node → Run store → Planning projection → ANSWER node와
  Draft consumer를 합성 Provider payload로 연결했다. spoof 반례, exact version, missing/old
  fallback, multiline title, 여러 chunk, recovery marker, segment rehydrate를 포함한다.
- 실제 모델 생성/Live Provider 호출·변경 **0**. CPU 검사는 모델과 겹치지 않았다.

이 결과는 코드 경계 및 fake component 회귀 통과다. 새 Canonical92/업무 성공률이 아니다.
기존 T3의 LLM `needsAction → 진행 중` 오답은 excerpt의 metadata 덮어쓰기에서 발생한
오류가 아니므로 이번 수정으로 해결됐다고 하지 않는다. RU의 불필요 WRITE 및 Source/시간
판단 오류도 남아 있다. 과거 결과와 실패 Trial은 보존한다.

판정: **관측 필드 authority와 동일 객체 materialization 경계 ADOPT**.
