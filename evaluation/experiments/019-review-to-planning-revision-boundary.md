# 019. Review REVISE → Planning 수정 입력의 최초 손실 경계

기준 `b02ad1eb`. 017의 실제 producer 연결에서는 023 PASS, 028 허위
CONFIRM, 021 Planning Schema 실패였으므로 올바른 REVISE 후 수정 완료를
관측하지 못했다. 017 합성 WRONG_ACTION_DATE와 FORBIDDEN_ATTENDEE는
Review finding과 aggregate REVISE까지 확인했지만 Planning 수정은
실행하지 않았다. 따라서 이 기록은 수정 경로 **정적 계약 진단**이며 모델
품질·복구율 평가가 아니다.

현재 `route_plan_review`는 REVISE를 `PLANNING_REVISE_PLAN`으로 보내며
`plan_review`를 State에 둔다. `PlanningInputState`도 `plan_review`를
허용한다. 그러나 `PlanningSubgraph._project_runtime_inputs`는 이를
수정 문맥으로 만들지 않고,
`project_draft_action_objective_per_output_route_input` 및
`project_compose_arguments_per_output_route_input`은 이전 Plan/Review issue를
모델 입력에 투영하지 않는다. 두 제품 Prompt source도 이전 finding의
역할을 설명하지 않는다. 즉 경로 재진입은 있으나, 변경 이유와 기존 잘못된
Plan 사이의 관계가 현재 LLM 호출에서 소실된다. 이때 같은 입력으로
재생성한 결과가 우연히 좋아질 수는 있지만 **Review 지적에 따라 수정한
것으로 증명되지 않는다**.

다음 후보는 전역 State나 특수 Case 규칙이 아니라, 이미 검증된
`ReviewReviseV2.issues`와 이전 `planning_result.actions`를 현재 frozen
route/action에 결속한 작은 revision projection이다. 이전 Plan은 실행 결과가
아닌 거절된 제안, finding은 사용자 요구보다 낮은 검토 정보임을 구별해야
한다. 초기 호출/다른 route에는 전달하지 않는다. 먼저 고정된 정상 Plan,
실제 내용 누락, wrong date, 금지된 effect, 사용자 Preview 수정과
반례에서 A/B를 비교하고, 그 뒤 동일 입력의 Planning→Review→수정→
Review RECHECK를 확인한다. 반복 실패 시 Prompt 문구 추가가 아니라
Planning 책임 경계를 다시 본다. 이번 SHA에서는 코드 활성화·실제 LLM
revision Trial·WRITE를 하지 않았으므로 이 수정 경로는 **미검증**이다.

후속 020에서는 이 문맥을 개발 전용 인자 작성 입력에 넣어 2개 합성 오류를
비교했으나, 현행 A도 둘 다 올바르게 생성해 개선 효과를 증명하지 못했다.
따라서 이 정적 손실만 근거로 Prompt/계약을 제품에 확대하지 않는다.
