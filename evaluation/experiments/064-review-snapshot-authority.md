# 064 — Review의 Source 사실 검증과 날짜-only 보존

기준 HEAD `df8abfb7`. #300의 Task/Calendar snapshot 연결 후 downstream Review를
추적하여 코드만으로 재현되는 두 결함과 같은 원리의 반례를 수정했다. 신규 모델 호출0.

## 최초 손실과 변경

| 경계 | 이전 결함 | 최소 수정 |
| --- | --- | --- |
|Review `exact_task_calendar_draft_plan`|Task title에 개행 후 `status: completed`가 있으면 실제상태 needsAction을 빠뜨린 Draft도 guard=True, findings=[]/LLM0. excerpt의 첫 상태 줄을 사실로 승격|같은Run/Evidence의 exact-version snapshot을 기존 store에서 해석. 본문 key:value 및 단어 존재 검사를 제거|
|동일 Review guard|정상 날짜-only Event의 time=None에 문자열 포함 검사를 적용해 TypeError|snapshot 기반 전체 예상 payload 검증으로 대체. 날짜-only를 시간과 혼동하지 않음|
|Planning Draft datetime formatter|날짜-only를 datetime으로 읽어 없는 T00:00 추가|date-only는 같은 날짜 문자열로 보존. 종일 Event의 exclusive end 날짜 변경0|

snapshot을 연결한 뒤에도 status 단어가 title/notes에 있다는 이유만으로 실제 상태가
본문에 반영됐다고 판단할 수 없다. 따라서 **기존 deterministic materializer가 같은
authoritative snapshot으로 만든 전체 expected payload와 실제 payload의 exact equality**만
이 좁은 fast path로 인정한다. 기존 recipient/action/citation 검사는 그대로 유지한다.

다른 정상 문체, missing/wrong/conflicting snapshot 또는 사실 차이는 결정적으로 FAIL로
만들지 않고 기존 semantic Review로 넘긴다. fast path의 출력 자체를 정답으로 조작하지 않는다.
추가 CC·누락한 상태·변경 날짜·다른 Resource 등도 동일하게 기존 Review를 받는다.

Review snapshot은 내부 optional 함수 인자로만 전달하며 persisted State/LLM Prompt에
추가하지 않는다. 새 State/Schema/Node/Edge, Prompt/manifest/LLM 호출 유형은 없다.
checkpoint 재작성0. 미결속 과거 Evidence는 기존 semantic Review로 안전하게 fallback한다.
공통 exact snapshot resolver는 Planning에서 Retrieval Source owner로 이동했고 중복 authority나
compatibility alias는 남기지 않았다. Canonical05/06/15 직접 영향 계약을 함께 정합화했다.

## 검증·회귀·비용

- 수정 전 실제 normalize/guard/inspector의 메모리 호출로 title-status spoof와 날짜-only
  TypeError를 각각 재현했다. 모델·Provider 없이 최초 실패를 확인했다.
- 직접 인접9파일 **96 PASS**, 변경 source7개 scoped mypy와 Ruff PASS.
- 루트 인접 회귀 **1,850 PASS / 8.05초**: RU/Retrieval/Planning/Review unit,
  LangGraph adapter, LangGraph/Prompt architecture 및 Planning/Review owner-local gate.
  위96개와 겹치므로 숫자를 합산하지 않는다. 전체 pytest는 실행하지 않았다.
- 정상 snapshot/위조 title·notes·description/실제 상태 누락/추가 CC/다른 문체,
  missing·wrong·conflicting version/다른Run/all-day/복수chunk/별개Resource를 포함한다.
- 실제 Review physical node → same-Run store → internal projection → inspector 연결을
  검사하고 snapshot이 State/Prompt로 유출되지 않음을 확인했다.
- 모델·외부업무 Provider READ/WRITE/SEND **0**. 단일 pytest 프로세스로 모델 실행과
  겹치지 않았다. 정확한 결정적 Preview는 해당 inspector LLM0, fallback은 기존 LLM1이다.
  과거 잘못 생략했던 검사가 이제 실행될 수 있으므로 총 호출/지연 개선이라고 주장하지 않는다.

판정: **코드 계약 수정 ADOPT**. Approval/Permission/Execution/Verification 의미를 바꾸지
않고 독립 Review 검증을 보존했다. 다른 Review dimension과 confirmation/사용자 수정 경로는
그대로다. 기존 source-target gate 전체의 업무 의미 적합성 및 실제 모델 Review 품질,
전체 Canonical92/connected business 성공률은 이번 fake component 결과로 증명하지 않는다.
RU의 Source/Output/Goal 잔여 실패도 별개로 계속 검증한다.
