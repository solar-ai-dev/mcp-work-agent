# 033. RECHECK 출력 조건의 실제 local structured-provider 호환성

기준 SHA `021224fa`; 채택 제품 계약 `4405f17d`는 열린 이전 issue와
빈 finding의 조합을 Schema/소비 경계에서 거절한다. 순수 계약·compiled
fake 테스트는 028의 실제 모델 호출이 새 conditional schema에서 그대로
작동하는지 증명하지 않는다.

사전 고정: 028 compiled 결과의 `WRONG_DATE_023`와
`FORBIDDEN_ATTENDEE_023`에서 실제 수정 후 RECHECK prompt_input 두 개만
재생한다. 같은 qwen3.5:9b digest/temp0/seed1729, 현 제품 Prompt manifest와
현 `review_recheck_output_schema`를 사용한다. 각 1회 총 최대 2 node 호출,
Provider READ/WRITE 0, 전체 92 0. 원 structured output, schema/repair
dispatch 수, issue assessment/finding, tokens/latency, 실패를 ignored result에
보존한다. 조건 schema를 Provider가 받아들이고 해결된 두 issue 유형에서
현재 finding이 비어 있으면 인접 개선의 계약 회귀가 없다는 국소 근거로 본다.
의미 안정성·Live 백엔드 RECHECK나 전체 성공률은 이 두 호출로 주장하지
않는다. timeout/repair 실패도 결과로 남긴다.

## 결과

두 호출 모두 현 제품 manifest + conditional schema에서 **첫 provider
dispatch 1회**로 structured output을 반환했다. 날짜·참석자 수정 입력은
각각 이전 issue 3개를 전부 RESOLVED, 새 finding 0으로 평가했다. 실제
출력을 Application `recheck_affected_dimensions` → `aggregate_review_findings`
소비 경계에 전달했을 때 둘 다 PASS였다. 이는 모델 output→consumer의
국소 연결 확인이며 028의 compiled 순환을 새 코드 SHA에서 모두 다시
실행한 것과 다르다. 기존 028 compiled 수정 전후 Action 검증은 유지한다.

두 입력 input 14,616+14,543=29,159, output 302+182=484 tokens;
node 경과 13,337+10,291=23,628ms. repair·timeout·Provider READ/WRITE 0.
원 출력과 fingerprint는 ignored
`evaluation/results/review-recheck-schema-provider-20260917/two-corrected.json`.
backend Live RECHECK 호출과 수정 순환 반복 안정성은 미검증이다.
