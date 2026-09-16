# 025. RECHECK의 제안 전후 관계 입력 후보

기준 `53842ae6`. 021의 실제 compiled 수정 순환에서 State는 직전
`plan_review.issues`와 수정 전 `planning_result`를 저장하지만 RECHECK LLM
입력에는 affected dimension·구 Action/Route ID와 현재 Plan만 들어간다.
021의 두 수정안은 같은 frozen route의 단일 Action을 재작성하면서
Action ID가 바뀌었다. ID만 치환한 021 후보와 시간 역할만 바꾼 024
후보는 실패했다. 이번 가설은 **ID 자체가 아니라 변경 관계의 부재**다.

개발 후보 B는 같은 route에 수정 전후 Action이 정확히 하나씩 있을 때만
`proposal_transition`을 전달한다. 내용은 이전/현재 artifact ref,
route 및 두 Action ID, 달라진 argument path의 old/new 값, 이전
finding의 dimension·kind·description·bound ID다. 이전 finding은
`historical_review_issues`로 표시하며 사용자 요구나 현재 결함으로
승격하지 않는다. 현재 Plan·Intent·Evidence와 output schema는 그대로다.
관계가 다대다/불명확하면 만들지 않는다. 실제 실행 결과가 아닌
수정된 제안이라는 phase도 명시한다. 새 Node·전역 State/도메인 필드·
Case별 값 판정은 만들지 않는다.

실행 전 고정 비교: 021 `WRONG_DATE_023`, `FORBIDDEN_ATTENDEE_023`의
수정 후 RECHECK와, 같은 요청·근거에서 기존 잘못된 Action을 유지한
반례 두 개. A/B 각 1회, 최대 8 LLM 호출, 순서 날짜 A/B, 금지 B/A,
미수정 날짜 B/A, 미수정 금지 A/B. temp 0/seed 1729, 설치된 021 모델
digest, 같은 Prompt source/output schema, 입력 fingerprint 보존.
첫 structured output에서 해결된 두 문제를 다시 지적하지 않고,
미수정 두 문제는 놓치지 않으며, 정상/근거 외 문제를 발명하지 않아야
유력하다. 단발 결과만으로 제품 채택하지 않고 compiled 경로 반복을
별도 확인한다. Provider READ/WRITE, 전체 92 평가는 0.

결과와 채택 판단은 모든 Trial 후 기록한다.

8회 모두 schema 완료, provider 호출 실패·repair 0. B는 미수정 날짜의
8월 9일 오류를 세 dimension에서 정확히 유지했지만, 수정된 날짜 Plan에
다시 생성 확인을 요구했다. 수정된 참석자 Plan에도 이미 정한 금지를
재확인했고, 미수정 참석자 Plan은 위반을 발견하면서도 REVISE가 아닌
확인 질문으로 표현했다. 전후 관계는 오류 탐지에 도움이 됐으나
`fresh findings` 하나만 생성하는 출력 책임에서 해결 여부와 새 문제를
혼합했다. **제품 미채택**. 동결 결과는 ignored
`evaluation/results/review-proposal-transition-20260917/node-comparison.json`.
다음에는 동일한 관계 입력으로 이전 문제의 해결 상태와 새 finding을
분리하는 output responsibility를 별도 비교한다.
