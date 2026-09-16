# 018. Review에서 Work Analysis 재판단 전달 검토

기준 SHA `2523f699`, 제품 후보 SHA `b68d3939`는 017의 제한적 Gmail 수신
metadata 분리.
고정 연결 입력 `evaluation/results/review-temporal-connected-20260916/retrieval-result.json`
의 023/028은 새 RU→합성 READ→Work Analysis→Planning 출력이다. 021은 Planning
`OUTPUT_SCHEMA_INVALID`라 Review 입력이 없다. 연결 결과의 요약 `0/3`은
`DOWNSTREAM_OUTPUT_NOT_EVALUATED`를 뜻하며 세 의미 실패가 아니다.

023 Review Goal은 finding 0/PASS. 028은 Run 기준시각을 받고 Gmail 수신
metadata envelope를 보지 않았으며 8/8 Plan을 유지했다. 그러나 FreeBusy
`busy_intervals: []`와 제안 09:00–09:30이 있는데도 슬롯 재확인을 ISSUE로,
참석자 `[]`인데 메일 발신자의 회사 주소 확보를 EVIDENCE_GAP로 냈다.
Work Analysis의 `action_necessity_reason`이 실행 필요와 근거 미확인을
섞는지 살펴본다. 최초 원인으로 확정하지 않는다.

개발 비교는 실제 저장된 023/028 Review prompt input에서 **Work Analysis
투영만 제외**하고 두 Node 호출을 직렬 실행한다. RequestIntent, Plan,
Evidence, Run 기준시각, Prompt source/output schema, 모델 digest,
temperature 0/seed 1729는 고정한다. 두 결과 모두 정상 Plan의 허위
finding이 없어야 추가 합성 반례를 보며, 하나라도 악화하거나 실패하면
이 축의 제품 채택을 중단한다. 합성 반례는 실제 연결 결과로 세지 않는다.
입력 SHA, 원출력, 토큰, 지연, 실패를 ignored result에 보존한다. 실제
Provider/WRITE/전체 E2E는 실행하지 않는다.

## 결과·판단

첫 실행은 개발 manifest가 이미 채택된 `run_reference_time`을 중복 등록하여
모델 dispatch 전에 실패했다. harness를 멱등화한 뒤 정해 둔 2호출만 실행했다.
둘 다 Schema는 완료했지만, 023은 실제 Plan의 제목이 정확한데 제목 불일치
ISSUE를 새로 만들었고, 028은 FreeBusy가 비어 있어도 09:00–09:30 제안이
검증되지 않았다는 허위 ISSUE를 유지했다. 합성 반례 확장은 중단한다.
`Work Analysis` 전체 제외는 필요한 관계를 지우며 문제를 해결하지 못해
**기각**한다. ignored 원입력/출력은
`evaluation/results/review-work-analysis-projection-20260916/result.json`에 있다.
이 진단은 2호출, 입력/출력 14,174/667 token, 21.7초였다.
