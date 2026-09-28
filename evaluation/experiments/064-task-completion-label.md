# 064 — Task completion 표시의 확정 매핑 수정

## 기존 raw에서 확인한 경계

Actual MainGraph T3(`064-core005-goal-output-main-t3`, HEAD `c8708b1d`)는 snapshot의
`status=needsAction`을 조회 결과 → 정규화 → Evidence → 실제 `compose_answer` 입력까지
보존했다. 해당 excerpt SHA256은
`52c8aafcaa93c8b87936c2699c21e9105eb7b2679ffa0a54a7984d44203940ef`다.
이 입력에는 업무 착수/진행 중이라는 사실이 없고, FIRST 답변에서 처음 해당 표현이 추가됐다.
이는 LLM의 completion enum 해석 오류이며 Provider/Evidence 전송 손실이 아니다.

Google Tasks의 [공식 Task 계약](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks)은
status를 `needsAction`/`completed`로 구분한다. `needsAction`은 미완료를 뜻하며
착수 또는 진행률을 증명하지 않는다. 현재 Task READ formatter도 이미 `미완료/incomplete`를 쓴다.

## 별개의 코드 결함과 최소 수정

`planning/materialize_task_calendar_draft_payload.py`는 같은 enum을 `진행 중/In progress`로
번역하고 있었다. 이 deterministic Draft formatter는 T3 READ 호출에 사용되지 않았으므로
T3 원인이라고 주장하지 않는다. 다만 동일한 Provider completion 사실을 과장하는 확정 코드
결함이어서 `미완료/Incomplete`로 고쳤다. 원 Provider status를 괄호 안에 유지한다.

Task/Calendar 조회 범위·identity·날짜·승인·Draft 생성 여부는 바꾸지 않았다. Prompt, State,
Schema, Node, Effect, Provider API 호출도 변경하지 않았다. 미지의 status는 원문 그대로
표시하며, completed와 Calendar confirmed의 기존 표현을 보존한다.

## 검증과 남은 실패

- 한국어/영어 × needsAction/completed/미지 상태의 직접 테스트와 실제 argument materialization
  consumer, 기존 Task READ projection을 포함해 **74 PASS**, Ruff/diff 검사 PASS.
- 신규 모델/실제 Provider 실행 **0**. 이 단위·consumer 검증은 실제 모델 답변 개선 점수가 아니다.
- **채택:** 확정 enum 표시 수정만 Product 반영. T3 `compose_answer`의 생성형 상태 표현 실패는
  미해결이며 이 변경으로 해결됐다고 처리하지 않는다.
- Task Source가 요구한 notes/identity 등을 제거해 deterministic READ fast-path를 억지로
  적용하지 않는다. 필요하면 별도의 typed 상태 의미 projection을 검토하되 기존 근거·raw enum과
  provenance를 유지해야 한다. 답변 문자열 치환이나 상태 검색조건을 조회 사실로 재사용하지 않는다.
