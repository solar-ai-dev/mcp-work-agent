# 028. 해결 판정 분리의 compiled 수정 순환 비교

기준 `53842ae6`, 후보 구현 working tree. 027의 dev Node 결과가
좋았으므로 021의 동결 여섯 입력을 같은 순서로 production-composition
`ReviewSubgraph → Supervisor → PlanningSubgraph → ReviewSubgraph`에
다시 넣는다. 이 실행은 개발 in-memory Evidence와 저장 Request를
사용하며 백엔드 Domain Run/실제 Provider READ·WRITE가 아니다.

사전 고정 6개 각 1 Trial: 정상 023, 잘못된 날짜, 금지 참석자,
Preview 제목 수정, 실제 메일 근거 부족, 정상 028. 첫 Review의
finding/disposition은 강제하지 않는다. 021과 입력 요청·Intent·
Evidence·Plan/model digest/temp0/seed1729를 고정하고 제품 Prompt·
Schema·RECHECK 전후 관계 Projection만 변경한다. 변경된 Prompt
입력 SHA는 기준과 달라지는 것이 정상이며 모두 저장한다. 021
baseline은 별도 결과로 유지한다. 최대 초기 Review 6, Planning 2,
RECHECK 2 subgraph invocation; 실패는 성공으로 대체하지 않는다.

채택 조건: 정상 두 입력 PASS 유지, 초기 날짜/금지 ISSUE를 놓치지
않고 Planning이 수정, RECHECK가 수정 해결을 인정해 PASS, 다른
요구가 보존돼야 한다. Preview/근거 부족은 기존 허위 판정을
개선하면 좋지만 이번 RECHECK-only 코드가 초기 Review를 고치지는
못하므로, 두 사례를 별도 잔여 실패로 정확히 유지한다. 호출·토큰·
지연·repair/timeout과 첫/최종 결과를 분리 기록한다. 실패하면
후보를 채택 완료로 두지 않는다. 전체 92/Live Provider I/O는 0.

결과와 채택 판단은 실행 후 기록한다.

## 결과

6개 동결 입력 모두 compiled 경로 완료, LLM dispatch 24/24,
repair·timeout 0. 021 baseline 대비 정상 023·028은 PASS 유지.
날짜/금지 위반은 초기 Review가 같은 3개 REVISE issue를 내고,
Planning이 각각 날짜를 8월 9일→8월 8일로, attendees 필드 제거로
수정했다. 다른 대상·시각·제목·근거가 유지됐고, 금지 사례의 설명은
동의어 수준으로 바뀌었다. 두 RECHECK 입력은 전후 같은 route의
단일 Action만 연결했고 과거 issue 각 3개를 모두 RESOLVED로
평가, 새 finding 0, 최종 PASS→DOMAIN_VALIDATION이었다.
021에서는 같은 수정 후 RETRIEVE_MORE/CONFIRM이었으므로 두 오류
유형의 실제 수정 순환이 개선됐다. RECHECK 원 structured output과
Supervisor target은 ignored `evaluation/results/review-resolution-compiled-20260917/connected.json`
에 모두 남겼다.

초기 Preview 제목 수정은 여전히 허위 REVISE, 실제 메일 근거 부족은
여전히 CONFIRM이다. 이 둘은 이번 RECHECK-only 변경의 개선으로
세지 않는다. Domain Validation 이후, 승인/실제 WRITE/Verification은
실행하지 않았다. 이번 후보는 RECHECK 2종의 연결 개선으로 채택하되
Review 전체 안정화는 아니다.

호출 24→24, 합계 input 266,670→270,532 tokens (+3,862),
output 6,351→5,154 (-1,197), stage 경과 합 285,891→249,113ms.
속도 차이는 단발 지연의 비교이지 지속적 latency 개선으로 주장하지
않는다. 증분 토큰은 전후 relation과 issue assessment를 포함한다.
Provider READ/WRITE, 공식 백엔드 Domain Run, LangSmith trace, 전체
92 범위는 이 실험에서 실행하지 않았다. backend/trace 검증은 별도다.
